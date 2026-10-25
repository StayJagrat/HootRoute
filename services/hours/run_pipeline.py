#!/usr/bin/env python
"""Run the whole hours-evidence pipeline: fetch -> match -> parse -> evidence file -> evaluation + hand-label template.

  python run_pipeline.py --mock                       # offline, synthetic Google data, rules parser, writes *.mock.json
  python run_pipeline.py --dry-run                    # show the Apify inputs and cost estimate only
  python run_pipeline.py                              # real: needs APIFY_TOKEN (+ ANTHROPIC_API_KEY for the claude/auto parser)
  python run_pipeline.py --skip-fetch --parser claude # re-use cached Apify results, parse everything with Claude

Output: data/cache/hours_evidence.json (real) or data/cache/hours_evidence.mock.json (--mock; override with --out).
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import evaluate, fetch_apify, make_handlabel_template, match_osm, parse_hours  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mock", action="store_true", help="no network, no keys")
    ap.add_argument("--dry-run", action="store_true", help="print Apify inputs/cost estimate and stop")
    ap.add_argument("--skip-fetch", action="store_true", help="use cached raw results")
    ap.add_argument("--skip-eval", action="store_true")
    ap.add_argument("--parser", choices=["rules", "claude", "auto"], help="default: rules with --mock, auto otherwise")
    ap.add_argument("--categories")
    ap.add_argument("--tiles", type=int, default=1)
    ap.add_argument("--budget-usd", type=float)
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--only-missing", action="store_true", help="evidence only for places with no OSM opening_hours")
    ap.add_argument("--eval-n", type=int, default=40)
    ap.add_argument("--out", help="evidence output path")
    a = ap.parse_args(argv)
    mock = ["--mock"] if a.mock else []
    parser = ["--parser", a.parser] if a.parser else []

    print("== 1/4 fetch ==")
    if a.dry_run:
        fetch_apify.main(["--dry-run", "--tiles", str(a.tiles)]
                         + (["--categories", a.categories] if a.categories else [])
                         + (["--budget-usd", str(a.budget_usd)] if a.budget_usd is not None else []))
        return
    if not a.skip_fetch:
        args = list(mock) + ["--tiles", str(a.tiles)]
        args += ["--categories", a.categories] if a.categories else []
        args += ["--budget-usd", str(a.budget_usd)] if a.budget_usd else []
        args += ["--refresh"] if a.refresh else []
        fetch_apify.main(args)
    print("== 2/4 match ==")
    match_osm.main(list(mock))
    print("== 3/4 parse -> evidence ==")
    pargs = list(mock) + parser + (["--only-missing"] if a.only_missing else []) + (["--out", a.out] if a.out else [])
    parse_hours.main(pargs)
    print("== 4/4 evaluation + hand-label template ==")
    make_handlabel_template.main(list(mock))
    if not a.skip_eval:
        evaluate.main(list(mock) + parser + ["--n", str(a.eval_n)])


if __name__ == "__main__":
    main()
