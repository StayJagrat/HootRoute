"""Offline routing regression benchmark. No provider keys, paid checks, or UI changes.

Run: python -X utf8 scripts/evaluate_routes.py
This checks route arithmetic and selection rules; it does not validate personal outcomes.
"""
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "engine"))
from hootroute_engine.engine import Engine


CASES = [
    ("Moscone to City Hall, Friday 23:30", (37.7842, -122.4016), (37.7793, -122.4193), 4, 1410),
    ("Powell to Civic Center, Friday 23:00", (37.7844, -122.4079), (37.7796, -122.4139), 4, 1380),
    ("Union Square to Ferry Building, Saturday 00:05", (37.7880, -122.4075), (37.7955, -122.3937), 5, 5),
    ("Moscone to City Hall, Sunday 23:55", (37.7842, -122.4016), (37.7793, -122.4193), 6, 1435),
]


def main():
    engine = Engine()
    for label, origin, destination, day, minute in CASES:
        result = engine.route("evaluation", origin, destination, day, minute)
        fastest = next(r for r in result["routes"] if r["id"] == "fast")
        recommended = next(r for r in result["routes"] if r["id"] == result["recommended"])
        assert recommended["score"] >= fastest["score"]
        assert recommended["minutes"] <= fastest["minutes"] * 1.25 + 0.2  # packed times round to tenths
        for route in result["routes"]:
            xy = [engine.W.proj.xy(lat, lon) for lon, lat in route["coords"]]
            length = sum(math.hypot(*(b - a)) for a, b in zip(xy, xy[1:]))
            assert 0 <= route["score"] <= 100
            assert route["score"] == round(sum(route["points"].values()), 1)
            assert 0 <= route["gap"]["m"] <= length + 1
            if route["gap"]["range"]:
                start, end = route["gap"]["range"]
                assert 0 <= start <= end <= length + 1
                assert abs((end - start) - route["gap"]["m"]) <= 1
        print(json.dumps({"case": label, "candidates": result["candidates"], "ms": result["ms"],
                          "recommended": recommended["id"], "score": recommended["score"], "minutes": recommended["minutes"],
                          "longestGapM": recommended["gap"]["m"], "checks": "passed"}), flush=True)


if __name__ == "__main__": main()
