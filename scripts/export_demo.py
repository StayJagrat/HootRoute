"""Write the engine-backed offline demo data used by the PWA.

Run from the repo root: .venv/bin/python scripts/export_demo.py
Use --check to verify the checked-in JSON still matches the engine and cache.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "engine"))
sys.path.insert(0, str(ROOT / "services" / "agents"))

from hootroute_agents.plan_data import build_demo_data  # noqa: E402
from hootroute_engine.engine import Engine  # noqa: E402

OUT = ROOT / "web" / "public" / "data" / "demo-route.json"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="fail if the offline JSON differs from the engine")
    args = parser.parse_args()
    expected = json.dumps(build_demo_data(Engine()), indent=2, ensure_ascii=False) + "\n"
    if args.check:
        if not OUT.exists() or OUT.read_text() != expected:
            raise SystemExit("Offline demo data differs; run scripts/export_demo.py")
        print("Offline demo data matches the engine")
        return
    OUT.write_text(expected)
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
