"""Run every agent from one process (uagents Bureau, mailbox-capable) or as one OS process per agent.

    python run_all.py                    # Bureau, all agents
    python run_all.py --only head        # just the ASI:One front door
Run the Head alone with:  python head_chat.py
"""
import argparse

from common import BUREAU_PORT, local_bureau_policy, mode


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--multiprocess", action="store_true"); ap.add_argument("--only", default="")
    args = ap.parse_args(); only = {x.strip() for x in args.only.split(",") if x.strip()} or None
    from uagents import Bureau
    from registry import build_all
    bureau = Bureau(port=BUREAU_PORT, endpoint=[f"http://127.0.0.1:{BUREAU_PORT}/submit"], registration_policy=local_bureau_policy()) if mode() == "local" else Bureau(port=BUREAU_PORT)
    for a in build_all(only): bureau.add(a); print(f"  {a.name:36s} {a.address}")
    bureau.run()


if __name__ == "__main__":
    main()
