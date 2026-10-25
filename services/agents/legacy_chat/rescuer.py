"""rescuer: triggered by the watcher when a walker stops replying. Writes a HANDOFF PACKET to a local file for the user's trusted contact.

It NEVER contacts emergency services, sends no texts or calls, and posts nothing anywhere. It only writes a file and tells the user so.
Run alone:  python rescuer.py
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone

from uagents import Context

from common import CORE, OUT_DIR, Engine, address_of, make_agent
from models import RescueDone, RescueTrigger


def _hav(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1])); h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371000 * 2 * math.asin(math.sqrt(h))


async def nearby_open_help(coords: list[list[float]], engine: Engine, radius: float = 150.0, limit: int = 8) -> list[dict]:
    """Places the engine says are open right now (flag 1) within `radius` m of the route. Best effort: empty list if the engine is down."""
    try: rows = await engine.places("rescuer")
    except Exception: return []
    pts = [(c[1], c[0]) for c in coords]; out = []
    for r in rows:                         # [id, lat, lon, name, cat, open(1/0/-1), declared]
        if r[5] != 1: continue
        d = min(_hav((r[1], r[2]), p) for p in pts)
        if d <= radius: out.append(dict(name=r[3], category=r[4], lat=r[1], lon=r[2], metres_from_route=round(d)))
    return sorted(out, key=lambda x: x["metres_from_route"])[:limit]


def _dur(minutes: float) -> str: return f"{minutes * 60:.0f} s" if minutes < 2 else f"{minutes:.0f} min"


def build_rescuer():
    agent = make_agent(CORE["rescuer"]["name"], CORE["rescuer"]["seed_env"], CORE["rescuer"]["port"], "rescuer.md")
    engine = Engine()

    @agent.on_message(RescueTrigger, replies=RescueDone)
    async def on_trigger(ctx: Context, sender: str, msg: RescueTrigger):
        if sender != address_of("watcher"): ctx.logger.warning("RescueTrigger from non-watcher ignored"); return
        ts = datetime.now(timezone.utc); packet = dict(
            kind="streetwise-handoff-packet", created_utc=ts.isoformat(), walk=msg.label, destination=msg.destination, reason=msg.reason, minutes_without_reply=round(msg.minutes_overdue, 1),
            last_known="Exact position is not tracked. The planned route polyline is below; the walker was somewhere along it.",
            route_lonlat=msg.route_coords, route_start_latlon=[msg.route_coords[0][1], msg.route_coords[0][0]] if msg.route_coords else None,
            route_end_latlon=[msg.route_coords[-1][1], msg.route_coords[-1][0]] if msg.route_coords else None,
            open_places_near_route=await nearby_open_help(msg.route_coords, engine) if msg.route_coords else [],
            instructions_for_trusted_contact=["Try to call or text the walker now.", "If you cannot reach them and are worried, call 911 yourself and share this packet.",
                                              "Streetwise did not contact anyone and did not alert any emergency service."],
            emergency_services_contacted=False)
        OUT_DIR.mkdir(parents=True, exist_ok=True); path = OUT_DIR / "handoffs" / f"handoff_{ts.strftime('%Y%m%dT%H%M%SZ')}_{msg.session[-6:]}.json"
        path.parent.mkdir(parents=True, exist_ok=True); path.write_text(json.dumps(packet, indent=2))
        ctx.logger.warning(f"handoff packet written: {path} (no emergency services contacted)")
        summary = (f"I did not hear back from you for {_dur(msg.minutes_overdue)}, so I prepared a handoff packet for your trusted contact (route, time, open places nearby): {path}. "
                   "I have NOT contacted emergency services or anyone else. If you need emergency help, call 911. If you are okay, reply **ok** or **stop walk**.")
        await ctx.send(sender, RescueDone(session=msg.session, user=msg.user, packet_path=str(path), summary=summary))

    return agent


if __name__ == "__main__":
    a = build_rescuer(); print(f"rescuer address: {a.address}"); a.run()
