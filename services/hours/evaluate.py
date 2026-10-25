"""Evaluation harness: how well does the parse stage recover trusted OSM hours from the fetched source text alone?

Sample N (default 40) places that have BOTH
  * an OSM `opening_hours` value we trust (strict-valid, opens at least once a week), and
  * a fetched Google source text (not a "closed" flag),
run ONLY the parse stage on the source text (the OSM value is never shown to the parser), then compare the parsed
schedule to the OSM schedule with the engine's own `is_open` on every 30 minutes of the week (336 slots).

Reports
  * slot agreement      : mean % of half-hour slots where parsed and OSM agree (open/closed)
  * places >= 95%       : % of sampled places whose agreement is at least 95 %
  * null rate, exact-string matches, per-shape breakdown, baseline (no hours = always closed)
Disagreement has two causes that cannot be separated on real data: parser mistakes and genuine source differences
(OSM stale or Google stale). On --mock data the injected stale cases are flagged, so parser accuracy can be read off.

  python evaluate.py --mock [--n 40] [--seed 7] [--all]
  python evaluate.py --parser claude        # real data, Claude parser (needs ANTHROPIC_API_KEY)
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hours_common import CACHE, WEEK_SLOTS, agreement, osm_truth_eligible, read_json, suffix, week_vector, write_json  # noqa: E402
from parse_hours import Parser  # noqa: E402

CLOSED_FLAG_TEXT = ("permanently closed", "temporarily closed")


def wilson(k: int, n: int, z: float = 1.96):
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def shape(text: str) -> str:
    return "day-list (Google openingHours)" if text.lstrip().startswith(("Monday:", "Tuesday:", "Wednesday:")) else "free-text"


def evaluate(matches: list[dict], n: int, seed: int, parser_mode: str, use_all: bool = False) -> dict:
    excl = dict(no_source_text=0, google_says_closed=0, osm_hours_unusable_as_truth=0, no_osm_hours=0)
    pool = []
    for m in matches:
        if not m.get("osm_hours"):
            excl["no_osm_hours"] += 1
        elif not osm_truth_eligible(m["osm_hours"]):
            excl["osm_hours_unusable_as_truth"] += 1
        elif not m.get("source_text"):
            excl["no_source_text"] += 1
        elif m["source_text"].strip().lower() in CLOSED_FLAG_TEXT:
            excl["google_says_closed"] += 1
        else:
            pool.append(m)
    rng = random.Random(seed)
    sample = pool if use_all else rng.sample(pool, min(n, len(pool)))
    parser = Parser(parser_mode)
    rows = []
    for m in sample:
        r = parser.parse(m["source_text"])                                 # source text ONLY
        parsed = r["opening_hours"]
        rows.append(dict(place_id=m["osm_id"], name=m["osm_name"], osm_hours=m["osm_hours"], source_text=m["source_text"],
                         parsed=parsed, parse_conf=r["confidence"], notes=r["notes"], method=r["method"], shape=shape(m["source_text"]),
                         agreement=round(agreement(parsed, m["osm_hours"]), 4), exact=parsed == m["osm_hours"],
                         baseline_agreement=round(agreement(None, m["osm_hours"]), 4), mock_stale=bool(m.get("_mock_stale"))))
    parser.save()

    def summ(rs):
        k = len(rs)
        if not k:
            return dict(places=0)
        ge95 = sum(r["agreement"] >= 0.95 for r in rs)
        lo, hi = wilson(ge95, k)
        return dict(places=k,
                    slot_agreement_pct=round(100 * sum(r["agreement"] for r in rs) / k, 1),
                    places_ge95_pct=round(100 * ge95 / k, 1), places_ge95_ci95=[round(100 * lo, 1), round(100 * hi, 1)],
                    parsed_null=sum(r["parsed"] is None for r in rs),
                    exact_string_match=sum(r["exact"] for r in rs),
                    baseline_no_hours_slot_agreement_pct=round(100 * sum(r["baseline_agreement"] for r in rs) / k, 1))

    out = dict(parser=parser_mode, n_requested=n, seed=seed, eligible_pool=len(pool), excluded=excl, overall=summ(rows),
               by_shape={s: summ([r for r in rows if r["shape"] == s]) for s in sorted({r["shape"] for r in rows})})
    if any(r["mock_stale"] for r in rows) or any(m.get("_mock_kind") for m in matches):
        out["mock_diagnostics_only"] = dict(
            note="synthetic data: some Google hours were deliberately made stale vs OSM; excluding those isolates parser accuracy",
            stale_injected_in_sample=sum(r["mock_stale"] for r in rows),
            excluding_stale=summ([r for r in rows if not r["mock_stale"]]))
    out["worst"] = sorted(rows, key=lambda r: r["agreement"])[:6]
    out["rows"] = rows
    return out


def print_report(res: dict, title: str):
    o = res["overall"]
    print(f"\n=== {title} | parser={res['parser']} | sample={o['places']} of {res['eligible_pool']} eligible (seed {res['seed']}) ===")
    print(f"excluded from pool: {res['excluded']}")
    print(f"slot agreement (30-min slots, whole week): {o['slot_agreement_pct']}%")
    print(f"places with >=95% agreement              : {o['places_ge95_pct']}%   (95% CI {o['places_ge95_ci95'][0]}-{o['places_ge95_ci95'][1]}%)")
    print(f"parser returned null: {o['parsed_null']}   exact string equal: {o['exact_string_match']}   "
          f"baseline 'no hours = closed' slot agreement: {o['baseline_no_hours_slot_agreement_pct']}%")
    for s, v in res["by_shape"].items():
        print(f"  {s:32s} n={v['places']:3d} slots={v['slot_agreement_pct']}% >=95%: {v['places_ge95_pct']}%")
    if "mock_diagnostics_only" in res:
        d = res["mock_diagnostics_only"]
        e = d["excluding_stale"]
        print(f"  [mock only] {d['stale_injected_in_sample']} injected-stale pairs in sample; excluding them: "
              f"slots={e['slot_agreement_pct']}% >=95%: {e['places_ge95_pct']}% (n={e['places']})")
    print("worst cases:")
    for r in res["worst"][:4]:
        print(f"  {r['agreement']:.2f} {r['name']!r}: osm={r['osm_hours']!r} parsed={r['parsed']!r} src={r['source_text'][:70]!r}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mock", action="store_true")
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--all", action="store_true", help="evaluate every eligible place instead of a sample")
    ap.add_argument("--parser", choices=["rules", "claude", "auto"], help="default: rules with --mock, auto otherwise")
    ap.add_argument("--matches", type=Path)
    ap.add_argument("--out", type=Path)
    a = ap.parse_args(argv)
    mf = a.matches or CACHE / f"hours_matches_{suffix(a.mock)}.json"
    if not mf.exists():
        if not a.mock:
            raise SystemExit(f"{mf} missing: run fetch_apify.py and match_osm.py first")
        import fetch_apify, match_osm
        fetch_apify.main(["--mock"]); match_osm.main(["--mock"])
    mode = a.parser or ("rules" if a.mock else "auto")
    res = evaluate(read_json(mf)["matches"], a.n, a.seed, mode, a.all)
    out = a.out or CACHE / f"hours_eval_{suffix(a.mock)}{'_all' if a.all else ''}.json"
    write_json(out, res, indent=1)
    print_report(res, "ALL ELIGIBLE" if a.all else f"SAMPLE N={a.n}")
    print(f"\nwrote {out}")
    return res


if __name__ == "__main__":
    main()
