"""Pre-compute the neighbourhood reference distributions (Norm) for every 2 km cell of the city, so the first route in a
neighbourhood answers in about a second. Results land in data/cache/norms/.

    .venv/bin/python scripts/warm_norms.py                 # Fri/Sat/Sun at 10 PM, 11 PM, 1 AM (the planner's time chips)
    .venv/bin/python scripts/warm_norms.py --days 4 --minutes 1380
"""
import argparse, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "engine"))
from streetwise_engine.engine import Engine  # noqa: E402
from streetwise_engine.scoring import Ctx, Norm  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--days", type=int, nargs="*", default=[4, 5, 6])
ap.add_argument("--minutes", type=int, nargs="*", default=[22 * 60, 23 * 60, 60])
a = ap.parse_args()
e = Engine(); W = e.W
cells = sorted({Norm.cell_of(p) for p in W.node_p})
print(f"{len(cells)} cells x {len(a.days)} days x {len(a.minutes)} times", flush=True)
t0 = time.time(); n = 0
for day in a.days:
    for minute in a.minutes:
        for c in cells:
            d = day if minute >= 12 * 60 else (day + 0) % 7
            e.norm(Ctx(d, minute), ((c[0] + 0.5) * Norm.CELL, (c[1] + 0.5) * Norm.CELL)); n += 1
        print(f"day {day} minute {minute}: done ({n} norms, {time.time() - t0:.0f}s)", flush=True)
