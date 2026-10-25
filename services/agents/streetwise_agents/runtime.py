"""Hosts the four agents (Head, Guide, Checker, Rescuer) for every active walk. The gateway hands it room envelopes; it hands back agent messages.

`tell()` is the agent-to-agent channel. In-process it is a direct call; under uAgents (bridge.py) the same calls travel as
uAgents messages between the registered agents. Either way each hand-off is logged so the control room shows it.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable

from .agents import Checker, Guide, Head, Rescuer
from .engine_port import EnginePort
from .notify import Notifier
from .walk import Walk, effective_thresholds

log = logging.getLogger("streetwise.runtime")
Send = Callable[[str, dict], Awaitable[None]]       # (walk id, msg) -> publish into the walk's room

# Which agent owns each client message type.
ROUTE = {"walk.accept": "guide", "walk.start": "checker", "walk.position": "checker", "checkin.reply": "checker",
         "guardian.ack": "rescuer", "walk.end": "head", "audit.run": "head"}

TELL_LABEL = {("checker", "rescuer", "no_reply"): "No reply to the check-in. Escalating with last position and trace.",
              ("checker", "rescuer", "help"): "Walker held Help. Escalating now.",
              ("checker", "rescuer", "fine"): "Walker answered after escalation.",
              ("checker", "head", "arrived"): "Walker reached the destination. Head, please write the report.",
              ("checker", "guide", "replan"): "Walker left the route."}


class Runtime:
    def __init__(self, engine: EnginePort, send: Send, notifier: Notifier | None = None):
        self.engine = engine; self._send = send; self.notifier = notifier or Notifier()
        self.walks: dict[str, Walk] = {}
        self.agents = {a.name: a for a in (Head(self), Guide(self), Checker(self), Rescuer(self))}
        self.locks: dict[str, asyncio.Lock] = {}
        self._ticker: asyncio.Task | None = None

    # ---------- plumbing ----------
    async def send(self, w: Walk, msg: dict): await self._send(w.id, msg)

    async def tell(self, frm: str, to: str, w: Walk, event: str, **data):
        label = TELL_LABEL.get((frm, to, event))
        if label: await self.agents[frm].log(w, label, data.get("reason") or event.replace("_", " "), to.capitalize())
        await self.deliver(frm, to, w, event, data)

    async def deliver(self, frm: str, to: str, w: Walk, event: str, data: dict):
        """Transport for agent-to-agent messages. In-process: a direct call. live_bureau.py overrides it with uAgents messages."""
        await self.receive(to, w, event, data)

    async def receive(self, to: str, w: Walk, event: str, data: dict):
        a = self.agents[to]
        if to == "rescuer":
            if event in ("no_reply", "help"): await a.escalate(w, data.get("reason") or "Walker asked for help")
            elif event == "fine": await a.fine(w, data.get("via", "tap"))
        elif to == "head" and event == "arrived": await a.arrived(w)
        elif to == "guide" and event == "replan": await a.replan(w, data["at"])

    def lock(self, walk_id: str) -> asyncio.Lock: return self.locks.setdefault(walk_id, asyncio.Lock())

    def start(self):
        if self._ticker is None: self._ticker = asyncio.create_task(self._tick_loop())

    async def stop(self):
        if self._ticker: self._ticker.cancel(); self._ticker = None

    async def _tick_loop(self):
        while True:
            await asyncio.sleep(1.0 if not any(w.replay for w in self.walks.values()) else 0.25)
            now = time.time()
            for w in list(self.walks.values()):
                if not w.active: continue
                try:
                    async with self.lock(w.id):
                        await self.agents["checker"].tick(w, now); await self.agents["rescuer"].tick(w, now)
                except Exception: log.exception("tick failed for %s", w.id)
            for wid in [k for k, w in self.walks.items() if w.status == "ended" and now - (w.started or now) > 3600]:
                self.walks.pop(wid, None); self.locks.pop(wid, None)

    # ---------- entry points used by the gateway ----------
    @staticmethod
    def make_walk(record: dict, guardian_url: str) -> Walk:
        return Walk(id=record["id"], walker=record["walker_name"], guardian=record["guardian_name"], guardian_phone=record.get("guardian_phone"),
                    guardian_url=guardian_url, origin=record["origin"], dest=record["destination"], day=record["depart_day"], minute=record["depart_minute"],
                    choice=record["choice"], replay=record["replay"], time_scale=record["time_scale"],
                    backup_name=record.get("backup_name"), backup_phone=record.get("backup_phone"),
                    thresholds=effective_thresholds(record["thresholds"], record["replay"], record["time_scale"]))

    async def request(self, record: dict, guardian_url: str, cached: tuple[dict, dict] | None = None):
        w = self.make_walk(record, guardian_url); self.walks[w.id] = w
        async with self.lock(w.id): await self.agents["guide"].request(w, cached)

    def restore(self, record: dict, guardian_url: str, history: list[dict], routes: dict | None):
        """After a restart: rebuild an unfinished walk from its record and room history so the Watcher keeps watching."""
        w = self.make_walk(record, guardian_url)
        plan = next((e["msg"]["plan"] for e in reversed(history) if e["msg"].get("type") == "walk.plan"), None)
        if not plan or not routes: return None
        w.set_plan(plan["data"], routes); w.status = "planned"
        for e in history:
            t = e["msg"].get("type")
            if t == "walk.accept": w.set_choice(e["msg"].get("choice", "streetwise"))
            elif t == "walk.start": w.status, w.started, w.moved_ts = "walking", e["ts"] / 1000, time.time()
            elif t == "checkin.ask": w.status, w.reply_deadline, w.checkins = "checkin", e["msg"]["deadline"] / 1000, w.checkins + 1
            elif t == "checkin.reply" and e["msg"].get("reply") == "fine" and w.status in ("checkin", "escalated"): w.status = "walking"
            elif t == "guardian.alert": w.status, w.escalate_deadline, w.escalated_reason = "escalated", e["ts"] / 1000 + w.thresholds["escalateSeconds"], e["msg"]["reason"]
            elif t == "guardian.ack": w.acked_by = e["msg"].get("by")
            elif t == "rescue.ladder" and isinstance(e["msg"].get("step"), int): w.ladder = max(w.ladder, e["msg"]["step"])
            elif t == "walk.end": w.status = "ended"
        if w.status == "ended": return None
        self.walks[w.id] = w; return w

    async def handle(self, env: dict):
        """A client envelope that the gateway already validated and relayed: hand it to the agent that owns its type."""
        to = ROUTE.get(env["msg"]["type"])
        if to: await self.route(to, env)

    async def route(self, to: str, env: dict):
        """Transport for room envelopes. In-process: a direct call. live_bureau.py sends them to the owning uAgent."""
        await self.handle_at(to, env)

    async def handle_at(self, to: str, env: dict):
        w = self.walks.get(env["walkId"]); msg = env["msg"]; kind = msg["type"]
        if kind == "audit.run":
            async with self.lock(env["walkId"]): await self.agents["head"].run(w)
            return
        if not w: return
        async with self.lock(w.id):
            if kind == "walk.accept": await self.agents["guide"].accept(w, msg["choice"])
            elif kind == "walk.start": await self.agents["checker"].start(w)
            elif kind == "walk.position": await self.agents["checker"].position(w, msg)
            elif kind == "checkin.reply": await self.agents["checker"].reply(w, msg["reply"], msg["via"])
            elif kind == "guardian.ack": await self.agents["rescuer"].ack(w, msg["by"])
            elif kind == "walk.end" and env.get("from") == "walker": await self.agents["head"].ended(w)

    async def place_update(self, place_id: str, decl: dict, near_walks: list[str]):
        for wid in near_walks:
            w = self.walks.get(wid)
            if w and w.status != "ended":
                async with self.lock(w.id): await self.agents["guide"].place_update(w, place_id, decl)

    async def audit(self, day: int, minute: int) -> dict:
        return await self.agents["head"].run(None, day, minute)

    def status(self, walk_id: str) -> dict | None:
        w = self.walks.get(walk_id)
        return None if not w else {"status": w.status, "meters": round(w.meters), "total": round(w.total()) if w.data else None, "offset": round(w.offset)}
