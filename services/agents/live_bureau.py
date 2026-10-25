"""Live walks under Fetch.ai uAgents (AGENT_RUNTIME=uagents on the gateway).

One Bureau runs the four registered HootRoute agents. They keep their ASI:One chat protocol, and each also speaks the
`hootroute-walk` protocol: room envelopes from the gateway go to the agent that owns them, and every hand-off between
agents (Checker → Rescuer, Checker → Head, Checker → Guide) is a uAgents message checked against the sender's address.
The walk logic is hootroute_agents (the same code the gateway runs in-process), so the two runtimes cannot drift.

    ../../.venv-agents/bin/python live_bureau.py        # bridge on BRIDGE_PORT (8110), Bureau on BUREAU_PORT (8100)
"""
from __future__ import annotations

import asyncio
import hmac
import json
import logging
import os
import sys
from pathlib import Path

asyncio.set_event_loop(asyncio.new_event_loop())          # uAgents builds agents on the current loop; Python 3.14 has none by default

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[0] / "engine"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(HERE.parents[1] / ".env")                    # same file the gateway reads (BRIDGE_SECRET, GATEWAY_URL, Twilio); services/agents/.env holds the seeds

import httpx  # noqa: E402
from aiohttp import web  # noqa: E402
from uagents import Bureau, Context, Model, Protocol  # noqa: E402

from common import BUREAU_PORT, local_bureau_policy, mode  # noqa: E402
from registry import build_all  # noqa: E402
from hootroute_agents.engine_port import EnginePort  # noqa: E402
from hootroute_agents.notify import Notifier  # noqa: E402
from hootroute_agents.runtime import Runtime  # noqa: E402
from hootroute_agents.walk import Walk  # noqa: E402
from hootroute_engine.engine import Engine  # noqa: E402

log = logging.getLogger("hootroute.bureau")
GATEWAY = os.environ.get("GATEWAY_URL", "http://127.0.0.1:8000").rstrip("/")
SECRET = os.environ.get("BRIDGE_SECRET", "")
BRIDGE_PORT = int(os.environ.get("BRIDGE_PORT", "8110"))
CORE_KEY = {"head": "head", "guide": "guide", "checker": "checker", "rescuer": "rescuer"}


class AgentTell(Model):
    """One agent handing a walk event to another (e.g. checker -> rescuer 'no_reply')."""
    walk_id: str
    event: str
    data: str


class RoomEnvelope(Model):
    """A validated client envelope from the gateway, delivered to the agent that owns its type."""
    envelope: str


class UAgentsRuntime(Runtime):
    def bind(self, uagents: dict):
        self.uagents = uagents; self.ctx = {k: a._build_context() for k, a in uagents.items()}
        self.addr = {k: a.address for k, a in uagents.items()}; self.trusted = set(self.addr.values())

    async def deliver(self, frm: str, to: str, w: Walk, event: str, data: dict):
        await self.ctx[frm].send(self.addr[to], AgentTell(walk_id=w.id, event=event, data=json.dumps(data)))

    async def route(self, to: str, env: dict):
        await self.ctx["head"].send(self.addr[to], RoomEnvelope(envelope=json.dumps(env)))   # head is the front door for the gateway


def walk_protocol(rt: UAgentsRuntime, name: str) -> Protocol:
    proto = Protocol(name="hootroute-walk", version="1.0.0")

    @proto.on_message(AgentTell)
    async def on_tell(ctx: Context, sender: str, msg: AgentTell):
        if sender not in rt.trusted: ctx.logger.warning(f"ignored AgentTell from {sender}"); return
        w = rt.walks.get(msg.walk_id)
        if not w: return
        async with rt.lock(w.id): await rt.receive(name, w, msg.event, json.loads(msg.data))

    @proto.on_message(RoomEnvelope)
    async def on_room(ctx: Context, sender: str, msg: RoomEnvelope):
        if sender not in rt.trusted: ctx.logger.warning(f"ignored RoomEnvelope from {sender}"); return
        await rt.handle_at(name, json.loads(msg.envelope))

    return proto


class Outbox:
    """Agent messages back to the gateway, strictly in order."""
    def __init__(self): self.q: asyncio.Queue = asyncio.Queue(); self.client = httpx.AsyncClient(timeout=10)

    async def send(self, walk_id: str, msg: dict): await self.q.put({"walkId": walk_id, "msg": msg})

    async def run(self):
        while True:
            item = await self.q.get()
            for attempt in range(3):
                try:
                    r = await self.client.post(f"{GATEWAY}/api/internal/publish", json=item, headers={"X-Bridge-Secret": SECRET})
                    if r.status_code < 500: break
                except httpx.HTTPError: pass
                await asyncio.sleep(0.5 * (attempt + 1))
            else:
                log.error("gateway unreachable; dropped %s for %s", item["msg"].get("type"), item["walkId"])


def bridge_app(rt: UAgentsRuntime) -> web.Application:
    def authorised(req: web.Request) -> bool: return bool(SECRET) and hmac.compare_digest(req.headers.get("X-Bridge-Secret", ""), SECRET)

    async def handle(req: web.Request):
        if not authorised(req): return web.json_response({"error": "unauthorised"}, status=401)
        body = await req.json(); kind = req.match_info["kind"]
        if kind == "request":
            cached = tuple(body["cached"]) if body.get("cached") else None
            asyncio.create_task(rt.request(body["record"], body["guardianUrl"], cached))
        elif kind == "envelope": await rt.handle(body["envelope"])
        elif kind == "place": asyncio.create_task(rt.place_update(body["placeId"], body["declaration"], body["walks"]))
        elif kind == "declarations": rt.engine.set_declarations({int(d): v for d, v in body["declared"].items()})
        elif kind == "share": await rt.set_sharing(body["walkId"], bool(body["active"]), body.get("guardianUrl"))
        elif kind == "audit": return web.json_response(await rt.audit(body["day"], body["minute"]))
        else: return web.json_response({"error": "unknown"}, status=404)
        return web.json_response({"ok": True})

    async def health(_): return web.json_response({"ok": True, "agents": rt.addr, "walks": len(rt.walks)})

    app = web.Application(); app.router.add_post("/{kind}", handle); app.router.add_get("/health", health); return app


async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if len(SECRET) < 16: raise SystemExit("BRIDGE_SECRET (16+ characters) must be set: without it anyone could drive the walk agents.")
    engine = await asyncio.to_thread(Engine); outbox = Outbox()
    rt = UAgentsRuntime(EnginePort(engine), outbox.send, Notifier(os.environ.get("TWILIO_ACCOUNT_SID", ""), os.environ.get("TWILIO_AUTH_TOKEN", ""), os.environ.get("TWILIO_FROM_NUMBER", "")))
    agents = build_all()                                   # the four core agents (Head also serves the ASI:One chat)
    by_name = {a.name: a for a in agents}
    from common import CORE
    core = {k: by_name[CORE[key]["name"]] for k, key in CORE_KEY.items()}
    rt.bind(core)
    for k, a in core.items(): a.include(walk_protocol(rt, k), publish_manifest=False)
    bureau = Bureau(port=BUREAU_PORT, endpoint=[f"http://127.0.0.1:{BUREAU_PORT}/submit"], registration_policy=local_bureau_policy()) if mode() == "local" else Bureau(port=BUREAU_PORT)
    for a in agents: bureau.add(a)
    runner = web.AppRunner(bridge_app(rt)); await runner.setup(); await web.TCPSite(runner, "127.0.0.1", BRIDGE_PORT).start()
    rt.start()
    for k, a in core.items(): log.info("%-8s %s", k, a.address)
    log.info("bridge listening on 127.0.0.1:%d, gateway %s", BRIDGE_PORT, GATEWAY)
    await asyncio.gather(bureau.run_async(), outbox.run())


if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())
