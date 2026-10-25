"""Fetch SFMTA temporary street closures (construction, events, shared spaces) for the Checker's route inspection.

Source: DataSF "Temporary Street Closures" (8x25-yybr), refreshed daily by SFMTA. Excludes Public Works and Police closures.
Writes data/cache/closures.json with closures ending today or later. Run it on a machine with internet, before the demo:

    .venv/bin/python scripts/fetch_closures.py
"""
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

OUT = Path(__file__).resolve().parents[1] / "data" / "cache" / "closures.json"
URL = "https://data.sf.gov/resource/8x25-yybr.json"


def lines_of(shape) -> list:
    if not isinstance(shape, dict): return []
    if shape.get("type") == "LineString": return [shape["coordinates"]]
    if shape.get("type") == "MultiLineString": return shape["coordinates"]
    return []


def main():
    today = datetime.now().strftime("%Y-%m-%dT00:00:00")
    rows, offset = [], 0
    while True:
        r = requests.get(URL, params={"$where": f"end_dt >= '{today}'", "$limit": 5000, "$offset": offset, "$order": "objectid"}, timeout=120)
        r.raise_for_status(); page = r.json(); rows += page
        if len(page) < 5000: break
        offset += 5000
    out = []
    for x in rows:
        ls = lines_of(x.get("shape"))
        if not ls: continue
        out.append(dict(id=x.get("case_num") or x.get("objectid"), type=(x.get("type") or "").strip(), name=(x.get("case_name") or "").strip(),
                        street=x.get("street"), **{"from": x.get("from_st"), "to": x.get("to_st")}, start=(x.get("start_dt") or "")[:10], end=(x.get("end_dt") or "")[:10],
                        info=(x.get("info") or "")[:200], status=x.get("status"), lines=[[[round(c[0], 6), round(c[1], 6)] for c in l] for l in ls]))
    OUT.write_text(json.dumps({"source": "DataSF 8x25-yybr (SFMTA Temporary Street Closures)", "fetched_at": time.strftime("%Y-%m-%d %H:%M"), "closures": out}))
    print(f"{len(out)} closures written to {OUT}")


if __name__ == "__main__":
    sys.exit(main())
