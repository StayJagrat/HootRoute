"""Score the filled-in handlabel CSV: how often does our_hours agree with what a human verified?

Agreement uses the engine's is_open on every 30 minutes of the week, same as evaluate.py.
Rows with an empty verified_hours are skipped. verified_hours may be OSM syntax or plain text; "closed" / "permanently
closed" / "gone" mean the place is not open (off).

  python score_handlabels.py [--csv handlabel_template.csv] [--out report.json]
"""
import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hours_common import HERE, agreement, validate_osm_hours  # noqa: E402
from parse_hours import parse_rules  # noqa: E402

GONE = {"closed", "permanently closed", "gone", "out of business", "does not exist", "n/a closed", "off"}


def normalise_verified(text: str):
    t = text.strip()
    if t.lower() in GONE:
        return "off", "closed"
    ok, _ = validate_osm_hours(t)
    if ok:
        return t, "osm"
    r = parse_rules(t)
    return r["opening_hours"], "parsed" if r["opening_hours"] else "unparseable"


def score(rows: list[dict]) -> dict:
    scored, skipped_blank, unparseable = [], 0, []
    for r in rows:
        v = (r.get("verified_hours") or "").strip()
        if not v:
            skipped_blank += 1; continue
        truth, how = normalise_verified(v)
        if truth is None:
            unparseable.append(r["place_id"]); continue
        ours = (r.get("our_hours") or "").strip() or None
        a = agreement(ours, truth)
        scored.append(dict(place_id=r["place_id"], name=r.get("name"), our_hours=ours, verified=truth, how=how, agreement=round(a, 4),
                           exact=ours == truth, verified_by=(r.get("verified_by") or "").strip() or "?"))
    k = len(scored)
    out = dict(rows_in_csv=len(rows), verified_rows=k, blank_skipped=skipped_blank, verified_text_unparseable=unparseable)
    if k:
        ge95 = sum(s["agreement"] >= 0.95 for s in scored)
        out.update(slot_agreement_pct=round(100 * sum(s["agreement"] for s in scored) / k, 1), places_ge95=ge95,
                   places_ge95_pct=round(100 * ge95 / k, 1), exact_string_match=sum(s["exact"] for s in scored),
                   by_verifier=dict(Counter(s["verified_by"] for s in scored)),
                   disagreements=sorted([s for s in scored if s["agreement"] < 0.95], key=lambda s: s["agreement"]))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", type=Path, default=HERE / "handlabel_template.csv")
    ap.add_argument("--out", type=Path)
    a = ap.parse_args(argv)
    with open(a.csv, newline="") as f:
        rows = list(csv.DictReader(f))
    res = score(rows)
    print(f"{res['verified_rows']} verified of {res['rows_in_csv']} rows ({res['blank_skipped']} blank)")
    if res["verified_rows"]:
        print(f"slot agreement: {res['slot_agreement_pct']}%   places >=95%: {res['places_ge95']}/{res['verified_rows']} = {res['places_ge95_pct']}%   "
              f"exact string: {res['exact_string_match']}")
        for d in res["disagreements"][:10]:
            print(f"  {d['agreement']:.2f} {d['name']!r}: ours={d['our_hours']!r} verified={d['verified']!r} by {d['verified_by']}")
    if res["verified_text_unparseable"]:
        print("could not read verified_hours for:", res["verified_text_unparseable"], "-> rewrite in OSM syntax")
    if a.out:
        a.out.write_text(json.dumps(res, indent=1))
    return res


if __name__ == "__main__":
    main()
