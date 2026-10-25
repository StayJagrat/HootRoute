"""Stage 1: fetch Google Maps place data (with opening hours) for the pilot bounding box via Apify.

Actor: compass/crawler-google-places  (https://apify.com/compass/crawler-google-places)
Input fields used (checked against the Actor's live input schema):
  searchStringsArray, customGeolocation (GeoJSON Polygon, [lng, lat], first == last point), maxCrawledPlacesPerSearch,
  language, skipClosedPlaces, scrapePlaceDetailPage (optional)
Output fields used: title, placeId, location{lat,lng}, address, categoryName, openingHours[{day,hours}],
  permanentlyClosed, temporarilyClosed.
Pricing seen on the Actor page: pay-per-event, $0.004 per scraped place on the FREE tier (no filters / add-ons used here).

One run per (category, tile). Raw results are cached to data/cache/hours_raw_<category>[_tN].json and reused on re-runs.
Token: env APIFY_TOKEN. Cost cap: per-run `max_total_charge_usd` plus a global --budget-usd across the whole stage.

  python fetch_apify.py --dry-run                 # print the exact inputs and a cost estimate, no network
  python fetch_apify.py --categories restaurant   # real run for one category
  python fetch_apify.py --mock                    # synthetic data derived from OSM, no network
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hours_common import CACHE, bbox_polygon, get_bbox, load_osm_places, now_iso, read_json, write_json  # noqa: E402

ACTOR = "compass/crawler-google-places"
DEFAULT_CATEGORIES = ["restaurant", "bar", "cafe", "fast food restaurant", "convenience store", "pharmacy", "bakery",
                      "pub", "liquor store", "clothing store", "hair salon", "bank"]
PRICE_PER_PLACE = 0.004          # FREE tier, USD (Actor page). Bronze+ tiers are cheaper.
MOCK_FILE = CACHE / "hours_raw_mock.json"


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


def tile_polygons(n: int) -> list[dict]:
    """Split the padded bbox into n x n closed GeoJSON polygons ([lng, lat])."""
    full = bbox_polygon()["coordinates"][0]
    w, s = full[0]
    e, nn = full[2]
    out = []
    for i in range(n):
        for j in range(n):
            s0, s1 = s + (nn - s) * i / n, s + (nn - s) * (i + 1) / n
            w0, w1 = w + (e - w) * j / n, w + (e - w) * (j + 1) / n
            ring = [[w0, s0], [w1, s0], [w1, s1], [w0, s1], [w0, s0]]
            out.append({"type": "Polygon", "coordinates": [[[round(x, 6), round(y, 6)] for x, y in ring]]})
    return out


def build_input(category: str, polygon: dict, max_per_search: int, detail_page: bool) -> dict:
    inp = {
        "searchStringsArray": [category],
        "customGeolocation": polygon,
        "maxCrawledPlacesPerSearch": max_per_search,
        "language": "en",
        "skipClosedPlaces": False,          # keep closed places: permanentlyClosed / temporarilyClosed are evidence too
    }
    if detail_page:
        inp["scrapePlaceDetailPage"] = True  # +cost; only needed if openingHours turns out to be missing from list results
    return inp


def raw_path(category: str, tile: int, tiles: int) -> Path:
    return CACHE / (f"hours_raw_{slug(category)}" + (f"_t{tile}" if tiles > 1 else "") + ".json")


def spent_so_far() -> float:
    tot = 0.0
    for f in glob.glob(str(CACHE / "hours_raw_*.json")):
        if f.endswith("_mock.json"):
            continue
        try:
            tot += float(read_json(Path(f)).get("cost_usd") or 0)
        except Exception:
            pass
    return tot


def run_real(args) -> list[Path]:
    token = os.environ.get("APIFY_TOKEN")
    cats = [c.strip() for c in args.categories.split(",") if c.strip()] if args.categories else DEFAULT_CATEGORIES
    polys = tile_polygons(args.tiles)
    plan = [(c, i, p) for c in cats for i, p in enumerate(polys)]
    est = len(plan) * args.max_per_search * PRICE_PER_PLACE
    print(f"plan: {len(plan)} run(s), worst case ~${est:.2f} at ${PRICE_PER_PLACE}/place, budget ${args.budget_usd:.2f}")
    if args.dry_run:
        for c, i, p in plan:
            print(json.dumps({"cache": raw_path(c, i, args.tiles).name, "input": build_input(c, p, args.max_per_search, args.detail_page)}))
        return []
    if not token:
        raise SystemExit("APIFY_TOKEN is not set. Sign up at apify.com, redeem the Cal Hacks coupon (APIFY_CAL_HACKS), "
                         "create a token at console.apify.com/account/integrations and export APIFY_TOKEN.")
    from apify_client import ApifyClient
    client = ApifyClient(token)
    written, spent = [], spent_so_far()
    for c, i, poly in plan:
        out = raw_path(c, i, args.tiles)
        if out.exists() and not args.refresh:
            print(f"cached  {out.name}")
            written.append(out); continue
        remaining = args.budget_usd - spent
        if remaining < 0.05:
            print(f"budget ${args.budget_usd:.2f} reached (spent ${spent:.2f}); stopping before {c!r}")
            break
        cap = min(remaining, args.per_run_cap_usd)
        inp = build_input(c, poly, args.max_per_search, args.detail_page)
        print(f"run     {c!r} tile {i}  (cap ${cap:.2f}) ...", flush=True)
        run = client.actor(ACTOR).call(run_input=inp, max_total_charge_usd=Decimal(str(round(cap, 2))),
                                       run_timeout=timedelta(minutes=args.timeout_min))
        if run is None:
            print("  no run returned, skipping"); continue
        get = (lambda k, camel: getattr(run, k, None) if not isinstance(run, dict) else run.get(camel))
        ds, rid, status = get("default_dataset_id", "defaultDatasetId"), get("id", "id"), get("status", "status")
        items = list(client.dataset(ds).iterate_items()) if ds else []
        cost = get("usage_total_usd", "usageTotalUsd")
        cost = float(cost) if cost is not None else round(len(items) * PRICE_PER_PLACE, 4)   # fallback: estimate
        spent += cost
        write_json(out, dict(actor=ACTOR, query=c, tile=i, tiles=args.tiles, fetched_at=now_iso(), run_id=str(rid),
                             status=str(status), cost_usd=cost, input=inp, items=items), indent=None)
        with_hours = sum(1 for it in items if it.get("openingHours"))
        print(f"  {len(items)} places, {with_hours} with openingHours, ${cost:.3f} (total ${spent:.2f}) -> {out.name}")
        written.append(out)
    return written


def run_mock(args) -> list[Path]:
    import mock_data
    items = mock_data.generate(load_osm_places())
    write_json(MOCK_FILE, dict(actor=ACTOR + " (MOCK)", query="*", fetched_at=now_iso(), cost_usd=0, items=items), indent=None)
    kinds = {}
    for it in items:
        kinds[it["_mock_kind"]] = kinds.get(it["_mock_kind"], 0) + 1
    print(f"mock: {len(items)} synthetic Google places derived from OSM -> {MOCK_FILE.name} {kinds}")
    return [MOCK_FILE]


def load_raw(mock: bool) -> list[dict]:
    """All cached raw items (deduped by placeId), each stamped with `_fetched_at` and `_query`."""
    files = [MOCK_FILE] if mock else [Path(f) for f in sorted(glob.glob(str(CACHE / "hours_raw_*.json"))) if not f.endswith("_mock.json")]
    seen, out = set(), []
    for f in files:
        if not f.exists():
            continue
        blob = read_json(f)
        for it in blob["items"]:
            pid = it.get("placeId") or it.get("cid") or json.dumps(it.get("location"), sort_keys=True) + str(it.get("title"))
            if pid in seen:
                continue
            seen.add(pid)
            it.setdefault("_fetched_at", blob.get("fetched_at"))
            it.setdefault("_query", blob.get("query"))
            out.append(it)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mock", action="store_true", help="no network: synthesize Google-like results from OSM places")
    ap.add_argument("--categories", help=f"comma list of search terms (default: {', '.join(DEFAULT_CATEGORIES)})")
    ap.add_argument("--tiles", type=int, default=1, help="split the area into N x N polygons per category (more coverage, more cost)")
    ap.add_argument("--max-per-search", type=int, default=300)
    ap.add_argument("--budget-usd", type=float, default=float(os.environ.get("HOURS_APIFY_BUDGET_USD", 10)),
                    help="stop launching runs when cumulative cost of cached runs reaches this (default 10)")
    ap.add_argument("--per-run-cap-usd", type=float, default=2.0, help="max_total_charge_usd passed to each Actor run")
    ap.add_argument("--timeout-min", type=int, default=20)
    ap.add_argument("--detail-page", action="store_true", help="also set scrapePlaceDetailPage (extra cost)")
    ap.add_argument("--refresh", action="store_true", help="ignore cache and re-run")
    ap.add_argument("--dry-run", action="store_true", help="print inputs + cost estimate, call nothing")
    a = ap.parse_args(argv)
    files = run_mock(a) if a.mock else run_real(a)
    if not a.dry_run:
        print(json.dumps(dict(stage="fetch", mock=a.mock, files=[f.name for f in files], places=len(load_raw(a.mock)))))


if __name__ == "__main__":
    main()
