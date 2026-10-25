"""Write handlabel_template.csv: 40 places the team can verify by phone or on foot.

Columns: place_id, name, address, our_hours, verified_hours, verified_by, notes
Selection (seeded): mostly places whose hours we are ADDING (no OSM hours), with a few lowest-confidence ones forced in,
plus ~10 places that already had OSM hours (cross-check the other direction).
Fill `verified_hours` in OSM syntax ("Mo-Fr 09:00-17:00; Sa 10:00-14:00", "24/7", "off") or plain text the rules parser
understands ("Mon-Fri 9am-5pm, Sat 10-2, Sun closed"), then run score_handlabels.py.

  python make_handlabel_template.py [--mock] [--n 40] [--seed 11]
"""
import argparse
import csv
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hours_common import CACHE, HERE, read_json, suffix  # noqa: E402

COLS = ["place_id", "name", "address", "our_hours", "verified_hours", "verified_by", "notes"]


def build(mock: bool, n: int, seed: int, evidence_path: Path | None = None):
    ev = read_json(evidence_path or CACHE / ("hours_evidence.mock.json" if mock else "hours_evidence.json"))
    matches = {m["osm_id"]: m for m in read_json(CACHE / f"hours_matches_{suffix(mock)}.json")["matches"]}
    rng = random.Random(seed)
    missing = [k for k in sorted(ev) if k in matches and not matches[k]["osm_hours"]]
    have = [k for k in sorted(ev) if k in matches and matches[k]["osm_hours"]]
    n_have = min(len(have), max(0, n // 4))
    n_missing = min(len(missing), n - n_have)
    low = sorted(missing, key=lambda k: ev[k]["confidence"])[: min(8, n_missing)]
    rest = [k for k in missing if k not in low]
    pick = low + rng.sample(rest, n_missing - len(low)) + rng.sample(have, n_have)
    if len(pick) < n:                                               # top up from whatever is left
        left = [k for k in sorted(ev) if k not in pick and k in matches]
        pick += rng.sample(left, min(n - len(pick), len(left)))
    rng.shuffle(pick)
    rows = []
    for k in pick:
        m = matches[k]
        rows.append(dict(place_id=k, name=m["osm_name"], address=m["osm_address"] or m["g_address"] or "", our_hours=ev[k]["opening_hours"],
                         verified_hours="", verified_by="",
                         notes=("MOCK DATA - regenerate with a real run before using. " if mock else "") +
                               f"conf={ev[k]['confidence']}; source text: {' / '.join(str(ev[k]['raw']).split(chr(10)))[:90]}"))
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mock", action="store_true")
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--out", type=Path, default=HERE / "handlabel_template.csv")
    a = ap.parse_args(argv)
    rows = build(a.mock, a.n, a.seed)
    with open(a.out, "w", newline="") as f:
        w = csv.DictWriter(f, COLS); w.writeheader(); w.writerows(rows)
    print(f"wrote {len(rows)} rows -> {a.out}")


if __name__ == "__main__":
    main()
