"""Print every agent's address (derived from its seed). Reads seeds from .env / environment. Prints a markdown table with --md."""
import sys

from common import CORE, address_of

rows = [(c["name"], k, address_of(k)) for k, c in CORE.items()]
if "--md" in sys.argv:
    print("| Agent | Role | Address |\n|---|---|---|"); [print(f"| {n} | {k} | `{a}` |") for n, k, a in rows]
else:
    for n, _, a in rows: print(f"{n:24s} {a}")
