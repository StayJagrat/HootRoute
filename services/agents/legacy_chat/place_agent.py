"""place_agent: one agent per shop. SIMULATED in the hackathon demo: hours come from demo_places.json, not from the business.

Run one alone:  python place_agent.py n4637773271      (place_id from demo_places.json)
"""
from __future__ import annotations

import os
import sys

from uagents import Context

from common import address_of, load_places, make_agent, place_cfg_by_id, slug
from models import HoursDeclaration, HoursQuery, HoursReply


def build_place_agent(cfg: dict):
    agent = make_agent(f"streetwise-place-{slug(cfg['name'])}", cfg["seed_env"], cfg["port"], "place_agent.md")
    pid, name, until, simulated = cfg["place_id"], cfg["name"], int(cfg["open_until"]), bool(cfg.get("simulated", True))

    @agent.on_message(HoursQuery, replies=HoursReply)
    async def on_query(ctx: Context, sender: str, msg: HoursQuery):
        if msg.place_id != pid:
            await ctx.send(sender, HoursReply(place_id=msg.place_id, name=name, open_at_minute=False, open_until=None, simulated=simulated, note="I only speak for " + pid)); return
        is_open = msg.minute <= until
        await ctx.send(sender, HoursReply(place_id=pid, name=name, open_at_minute=is_open, open_until=until if is_open else None, simulated=simulated,
                                          note="SIMULATED shop agent (demo)" if simulated else ""))
        ctx.logger.info(f"{name}: asked about minute {msg.minute}, open={is_open}")

    @agent.on_event("startup")
    async def announce(ctx: Context):
        if os.environ.get("PLACE_ANNOUNCE") == "1":        # optional: push the declaration to scout instead of waiting to be asked
            await ctx.send(address_of("scout"), HoursDeclaration(place_id=pid, name=name, open_until=until, simulated=simulated))

    return agent


if __name__ == "__main__":
    cfg = place_cfg_by_id(sys.argv[1]) if len(sys.argv) > 1 else load_places()[0]
    if cfg is None: sys.exit("unknown place_id; see demo_places.json")
    a = build_place_agent(cfg); print(f"{cfg['name']} address: {a.address}"); a.run()
