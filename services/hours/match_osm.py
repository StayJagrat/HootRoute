"""Stage 2: match fetched Google Maps places to OSM places.

A pair is a candidate only if BOTH hold:
  * haversine distance <= --max-m (default 30 m)
  * fuzzy name similarity >= --min-sim (default 0.72; difflib ratio on normalised names, plus a token-subset rule)
So a chain's other branch (same name, 100 m away) and a different shop next door (close, different name) are both rejected.
Candidates are assigned greedily by confidence, one-to-one (each OSM place and each Google place used at most once).

confidence = name_sim * (1 - 0.35 * distance / max_m)     in [0.65*sim, sim]

  python match_osm.py [--mock] [--max-m 30] [--min-sim 0.72]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_apify import load_raw  # noqa: E402
from hours_common import CACHE, haversine_m, load_osm_places, now_iso, suffix, write_json  # noqa: E402

STOP = {"the", "restaurant", "sf", "san", "francisco", "downtown", "inc", "llc", "co", "and", "of"}


def norm_name(s: str | None) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower().replace("&", " and ")
    s = re.sub(r"\(.*?\)", " ", s)
    s = re.sub(r"[^a-z0-9 ]", "", s.replace("-", " "))
    return " ".join(t for t in s.split() if t not in STOP)


def name_sim(a: str | None, b: str | None) -> float:
    def compare(left: str, right: str) -> float:
        na, nb = norm_name(left), norm_name(right)
        if not na or not nb:
            return 0.0
        r = SequenceMatcher(None, na, nb).ratio()
        ta, tb = set(na.split()), set(nb.split())
        shared = ta & tb
        if shared and (shared == ta or shared == tb) and sum(len(t) for t in shared) >= 5:
            r = max(r, 0.9)
        return r

    full = compare(a or "", b or "")
    # Google sometimes appends a search-keyword list after a spaced dash,
    # e.g. "Town Country Market - Sake, Fruits, Beer, Pharmacy, ...".
    # Compare the business name before that suffix too. Require two words so
    # a generic prefix such as "Market - ..." cannot match any nearby shop.
    short = (b or "").split(" - ", 1)[0]
    if short != (b or "") and len(norm_name(short).split()) >= 2:
        return max(full, compare(a or "", short))
    return full


def source_text(item: dict) -> str | None:
    """Single raw string the parse stage will read. Google closure flags win over stale hours."""
    if item.get("permanentlyClosed"):
        return "Permanently closed"
    if item.get("temporarilyClosed"):
        return "Temporarily closed"
    oh = item.get("openingHours")
    if isinstance(oh, list) and oh:
        parts = [f"{d.get('day')}: {d.get('hours')}" for d in oh if isinstance(d, dict) and d.get("hours")]
        return "; ".join(parts) or None
    if isinstance(item.get("openingHoursText"), str) and item["openingHoursText"].strip():
        return item["openingHoursText"].strip()
    return None


def match(osm: list[dict], google: list[dict], max_m: float = 30.0, min_sim: float = 0.72) -> dict:
    cands = []
    for gi, g in enumerate(google):
        loc = g.get("location") or {}
        if loc.get("lat") is None:
            continue
        for oi, o in enumerate(osm):
            if not o["name"]:
                continue
            if abs(o["lat"] - loc["lat"]) > 0.0006 or abs(o["lon"] - loc["lng"]) > 0.0008:      # ~65 m prefilter
                continue
            d = haversine_m(o["lat"], o["lon"], loc["lat"], loc["lng"])
            if d > max_m:
                continue
            sim = name_sim(o["name"], g.get("title"))
            if sim < min_sim:
                continue
            cands.append((sim * (1 - 0.35 * d / max_m), sim, d, oi, gi))
    cands.sort(key=lambda c: -c[0])
    used_o, used_g, matches = set(), set(), []
    for conf, sim, d, oi, gi in cands:
        if oi in used_o or gi in used_g:
            continue
        used_o.add(oi); used_g.add(gi)
        o, g = osm[oi], google[gi]
        matches.append(dict(osm_id=o["id"], osm_name=o["name"], osm_cat=o["cat"], osm_hours=o["hours"], osm_address=o["address"],
                            g_place_id=g.get("placeId"), g_title=g.get("title"), g_address=g.get("address"),
                            g_category=g.get("categoryName"), distance_m=round(d, 1), name_sim=round(sim, 3),
                            confidence=round(conf, 3), source_text=source_text(g), fetched_at=g.get("_fetched_at"),
                            **{k: g[k] for k in ("_mock_kind", "_mock_truth_osm_id", "_mock_stale") if k in g}))
    stats = dict(osm_places=len(osm), osm_named=sum(1 for o in osm if o["name"]), google_places=len(google), candidate_pairs=len(cands),
                 matched=len(matches), unmatched_google=len(google) - len(used_g), unmatched_osm=len(osm) - len(used_o),
                 matched_with_hours_text=sum(1 for m in matches if m["source_text"]),
                 matched_osm_without_hours=sum(1 for m in matches if not m["osm_hours"]),
                 osm_without_hours=sum(1 for o in osm if not o["hours"]))
    if any(g.get("_mock_kind") for g in google):                                       # self-check only possible on mock data
        bad = [m for m in matches if m.get("_mock_truth_osm_id") not in (None, m["osm_id"])]
        stats["mock_selfcheck"] = dict(
            wrong_osm_target=len(bad),
            decoys_total=sum(1 for g in google if g.get("_mock_kind") == "decoy"),
            decoys_matched=sum(1 for m in matches if m.get("_mock_kind") == "decoy"),
            far_total=sum(1 for g in google if g.get("_mock_kind") == "far"),
            far_matched=sum(1 for m in matches if m.get("_mock_kind") == "far"),
            google_only_matched=sum(1 for m in matches if m.get("_mock_kind") == "google_only"),
            true_total=sum(1 for g in google if g.get("_mock_kind") == "true"),
            true_matched=sum(1 for m in matches if m.get("_mock_kind") == "true"))
    return dict(matches=matches, stats=stats)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mock", action="store_true")
    ap.add_argument("--max-m", type=float, default=30.0)
    ap.add_argument("--min-sim", type=float, default=0.72)
    ap.add_argument("--out", type=Path)
    a = ap.parse_args(argv)
    google = load_raw(a.mock)
    if not google:
        raise SystemExit("no raw Google data found; run fetch_apify.py first" + ("" if a.mock else " (or use --mock)"))
    res = match(load_osm_places(), google, a.max_m, a.min_sim)
    out = a.out or CACHE / f"hours_matches_{suffix(a.mock)}.json"
    write_json(out, dict(generated_at=now_iso(), params=dict(max_m=a.max_m, min_sim=a.min_sim), **res), indent=None)
    print(json.dumps(dict(stage="match", out=str(out), **res["stats"])))
    return res


if __name__ == "__main__":
    main()
