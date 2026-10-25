"""The wire contract (streetwise-web/src/lib/types.ts) as seen by the gateway: who may send what, and envelope construction."""
from __future__ import annotations

import time
import uuid

ROLES = ("walker", "guardian", "shop", "room")

# Message types a connected client may send into a registered walk room. Everything an agent produces
# (walk.plan, voice.say, checkin.ask, escalate, guardian.alert, agent.log, audit.result) is rejected from clients,
# so nobody holding a walk link can forge an alert or a plan.
CLIENT_TYPES: dict[str, set[str]] = {
    "walker": {"walk.accept", "walk.start", "walk.position", "checkin.reply", "walk.end"},
    "guardian": {"guardian.join", "guardian.ack"},
    "room": {"audit.run", "walk.position"},      # walk.position from the control room only for replay walks (checked in rooms.py)
    "shop": set(),                               # shops declare hours over REST (POST /api/places/{id}/declaration)
}

AGENT_TYPES = {"rescue.ladder", "walk.plan", "voice.say", "checkin.ask", "escalate", "guardian.alert", "agent.log", "walk.end", "audit.result", "place.update", "walk.reset"}

# Room history kept for late joiners: only the newest of these types matters.
LATEST_ONLY = {"walk.position", "walk.plan", "audit.result", "guardian.join"}


def envelope(walk_id: str, msg: dict, sender: str = "engine") -> dict:
    return {"id": uuid.uuid4().hex, "walkId": walk_id, "ts": round(time.time() * 1000), "from": sender, "msg": msg}


def valid_lnglat(v) -> bool:
    return (isinstance(v, (list, tuple)) and len(v) == 2 and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in v)
            and -180 <= v[0] <= 180 and -90 <= v[1] <= 90)


def clean_client_msg(role: str, msg: dict) -> dict | None:
    """Validate and normalise one client message. Returns None when the message must be dropped."""
    kind = msg.get("type")
    if kind not in CLIENT_TYPES.get(role, set()): return None
    if kind == "walk.position":
        if not valid_lnglat(msg.get("lngLat")): return None
        num = lambda k, d=0.0: float(msg[k]) if isinstance(msg.get(k), (int, float)) and not isinstance(msg.get(k), bool) else d
        out = {"type": kind, "lngLat": [float(msg["lngLat"][0]), float(msg["lngLat"][1])], "heading": num("heading"), "speed": max(0.0, num("speed")),
               "progress": min(1.0, max(0.0, num("progress"))), "replay": bool(msg.get("replay"))}
        if isinstance(msg.get("accuracy"), (int, float)): out["accuracy"] = float(msg["accuracy"])
        return out
    if kind == "checkin.reply":
        if msg.get("reply") not in ("fine", "help"): return None
        return {"type": kind, "reply": msg["reply"], "via": "voice" if msg.get("via") == "voice" else "tap"}
    if kind == "walk.accept":
        return {"type": kind, "choice": "usual" if msg.get("choice") == "usual" else "streetwise"}
    if kind == "walk.start":
        return {"type": kind, "replay": bool(msg.get("replay"))}
    if kind == "walk.end":       # a walker may end their own walk early; arrival is decided by the agents
        return {"type": kind, "outcome": "ended", "summary": "Walk ended by the walker."}
    if kind == "guardian.join":
        return {"type": kind, "name": str(msg.get("name") or "Guardian")[:60]}
    if kind == "guardian.ack":
        return {"type": kind, "by": str(msg.get("by") or "Guardian")[:60]}
    if kind == "audit.run":
        return {"type": kind}
    return None
