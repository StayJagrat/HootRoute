"""End-to-end: a real gateway process, the real engine, the in-process agents, and WebSocket clients for every role.

    .venv/bin/python -m pytest services/api/tests -q
"""
import asyncio
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
import websockets

ROOT = Path(__file__).resolve().parents[3]
POWELL = {"lat": 37.7844, "lon": -122.4079, "name": "Powell St BART"}
CIVIC = {"lat": 37.7796, "lon": -122.4139, "name": "Civic Center BART"}


def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    port = free_port(); db = tmp_path_factory.mktemp("db") / "test.db"
    env = {**os.environ, "DB_PATH": str(db), "ADMIN_TOKEN": "", "TWILIO_ACCOUNT_SID": "", "CARTESIA_API_KEY": "", "PUBLIC_URL": f"http://127.0.0.1:{port}",
           "ANTHROPIC_API_KEY": "", "APIFY_TOKEN": "", "HOURS_CHECK_MOCK": "1", "HOURS_LIVE_FILE": str(db.parent / "hours_live.json")}
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "main:app", "--port", str(port), "--log-level", "warning"], cwd=ROOT / "services" / "api", env=env)
    base = f"http://127.0.0.1:{port}"
    for _ in range(120):
        try:
            if httpx.get(base + "/api/health", timeout=1).status_code == 200: break
        except httpx.HTTPError: pass
        time.sleep(0.5)
    else:
        proc.kill(); raise RuntimeError("gateway did not start")
    yield base
    proc.terminate(); proc.wait(10)


class Client:
    def __init__(self, ws): self.ws = ws; self.got: list[dict] = []

    @classmethod
    async def open(cls, base, walk, role, token=""):
        ws = await websockets.connect(f"{base.replace('http', 'ws')}/ws?walk={walk}&role={role}&token={token}")
        c = cls(ws); first = json.loads(await ws.recv()); assert first["kind"] == "history"; c.got += first["envelopes"]; return c

    async def send(self, msg, walk):
        await self.ws.send(json.dumps({"id": os.urandom(6).hex(), "walkId": walk, "ts": int(time.time() * 1000), "from": "walker", "msg": msg}))

    async def wait(self, kind, timeout=20.0, where=lambda m: True):
        for e in self.got:
            if e["msg"]["type"] == kind and where(e["msg"]): self.got.remove(e); return e["msg"]
        end = time.time() + timeout
        while time.time() < end:
            try: e = json.loads(await asyncio.wait_for(self.ws.recv(), end - time.time()))
            except asyncio.TimeoutError: break
            if e["msg"]["type"] == kind and where(e["msg"]): return e["msg"]
            self.got.append(e)
        raise AssertionError(f"no {kind} within {timeout}s; saw {[x['msg']['type'] for x in self.got][-15:]}")

    def types(self): return [e["msg"]["type"] for e in self.got]


def test_full_walk(server):
    asyncio.run(_full_walk(server))


async def _full_walk(base):
    async with httpx.AsyncClient(base_url=base, timeout=60) as http:
        assert (await http.get("/api/health")).json()["ok"]
        plan = (await http.post("/api/plans", json={"origin": POWELL, "destination": CIVIC, "day": 4, "minute": 23 * 60})).json()
        assert plan["planId"] and plan["route"] and plan["stats"]["hootroute"]["score"] >= plan["stats"]["shortest"]["score"]
        bad = await http.post("/api/plans", json={"origin": POWELL, "destination": {"lat": 40.0, "lon": -74.0}})
        assert bad.status_code == 422

        r = await http.post("/api/walks", json={"planId": plan["planId"], "origin": POWELL, "destination": CIVIC, "day": 4, "minute": 23 * 60,
                                                "walker": "Arya", "guardian": "Maya Chen", "guardianPhone": "415 555 0123", "replay": True, "timeScale": 60})
        assert r.status_code == 201, r.text
        walk = r.json(); wid, token = walk["walkId"], walk["walkerToken"]
        assert walk["guardianUrl"].endswith(f"/guardian/{wid}")

        # a guardian link cannot act as the walker
        with pytest.raises(Exception):
            bad_ws = await websockets.connect(f"{base.replace('http', 'ws')}/ws?walk={wid}&role=walker&token=wrong"); await bad_ws.recv()

        walker = await Client.open(base, wid, "walker", token)
        guardian = await Client.open(base, wid, "guardian")
        p = await walker.wait("walk.plan")
        data = p["plan"]["data"]; assert p["plan"]["guardian"] == "Maya Chen" and data["walker"]["name"] == "Arya"
        assert data["route"] == plan["route"], "the walk must run on the reviewed route"
        assert (await guardian.wait("walk.plan"))["plan"]["data"]["end"]["name"] == "Civic Center BART"

        # forged agent messages from a client are dropped
        await guardian.send({"type": "guardian.alert", "reason": "fake", "lngLat": [-122.4, 37.78], "where": "x"}, wid)
        await guardian.send({"type": "guardian.join", "name": "Maya"}, wid)
        assert (await walker.wait("guardian.join"))["name"] == "Maya"
        assert "guardian.alert" not in walker.types()

        await walker.send({"type": "walk.accept", "choice": "hootroute"}, wid)
        await walker.send({"type": "walk.start", "replay": True}, wid)
        await walker.wait("voice.say", where=lambda m: m["text"].startswith("Okay, I'm walking"))

        # walk to the engine's stop point on the empty stretch, then stand still
        from hootroute_engine import geo
        line = data["route"]; cum = geo.cumulative(line); stop_m = geo.project(line, data["stopAt"], cum)[0]
        for m in range(0, int(stop_m), 30):
            await walker.send({"type": "walk.position", "lngLat": geo.point_at(line, m, cum), "heading": 0, "speed": 1.35, "progress": 0, "replay": True}, wid)
            await asyncio.sleep(0.02)
        here = geo.point_at(line, stop_m, cum)
        await walker.send({"type": "walk.position", "lngLat": here, "heading": 0, "speed": 0, "progress": 0, "replay": True}, wid)
        ask = await walker.wait("checkin.ask", 10)
        assert "Still for" in ask["reason"]
        alert = await guardian.wait("guardian.alert", 10)           # no reply -> Rescuer
        assert " " in alert["where"] and alert["lngLat"] == pytest.approx(here, abs=1e-6)
        log = await walker.wait("agent.log", where=lambda m: m["agent"] == "rescuer" and "911 not contacted" in m["text"])
        assert "SMS: not configured" in log["text"]
        assert (await walker.wait("rescue.ladder", 10))["step"] == 0

        await guardian.send({"type": "guardian.ack", "by": "Maya"}, wid)
        await walker.wait("voice.say", where=lambda m: m["text"] == "Maya is on it.")
        await walker.send({"type": "checkin.reply", "reply": "fine", "via": "tap"}, wid)
        await walker.wait("agent.log", where=lambda m: "alert cleared" in m["text"])

        # shopkeeper on the route declares late hours -> place.update + re-scored plan
        place = data["places"][0]
        r = await http.post(f"/api/places/{place['id']}/declaration", json={"openUntil": "01:00", "safeHaven": True, "frontLight": True})
        assert r.json()["walksNotified"] >= 1
        upd = await walker.wait("place.update"); assert upd["place"]["openUntil"] == "01:00"
        await walker.wait("walk.plan", where=lambda m: "updated its hours" in m["plan"]["reason"])
        info = (await http.get(f"/api/places/{place['id']}")).json(); assert info["declaration"]["openUntil"] == "01:00"

        # finish the walk
        total = cum[-1]
        for m in range(int(stop_m), int(total) + 30, 40):
            await walker.send({"type": "walk.position", "lngLat": geo.point_at(line, m, cum), "heading": 0, "speed": 1.35, "progress": 0, "replay": True}, wid)
            await asyncio.sleep(0.02)
        end = await guardian.wait("walk.end", 10)
        assert end["outcome"] == "arrived" and end["summary"] and end["reportBy"].startswith(("template", "Claude"))
        rec = (await http.get(f"/api/walks/{wid}")).json(); assert rec["status"] == "ended" and rec["outcome"] == "arrived"

        # late joiner after the end sees no location trace
        late = await Client.open(base, wid, "guardian")
        assert "walk.position" not in late.types() and "walk.end" in late.types()

        # control room runs the overnight audit
        room = await Client.open(base, wid, "room")
        await room.send({"type": "audit.run"}, wid)
        res = await room.wait("audit.result", 60)
        assert res["ranking"] and res["draft311"].startswith("DRAFT — not submitted")
        for ws in (walker, guardian, late, room): await ws.ws.close()


def test_head_and_checker(server):
    """No Claude key in tests: the Head runs its fixed pipeline. The Checker's live check uses the labelled offline mock."""
    with httpx.Client(base_url=server, timeout=120) as http:
        r = http.post("/api/head/ask", json={"text": "from Moscone Center to City Hall, and check listed hours"}).json()
        tools = [t["tool"] for t in r["trace"]]
        assert r["by"].startswith("fixed pipeline") and r["planId"] and "plan_routes" in tools and "find_route_unknowns" in tools, r
        assert {t["agent"] for t in r["trace"]} <= {"guide", "checker"}
        if "check_listed_hours" in tools: assert r["check"]["mock"] and "after" in r
        ins = http.post("/api/check/route", json={"planId": r["planId"]}).json()
        assert ins["verdict"].startswith(("Good to go", "Heads up")) and ins["items"] and all(i["level"] in ("ok", "note", "warn") for i in ins["items"])
        assert "inspect_route" in tools
        u = http.post("/api/check/unknowns", json={"planId": r["planId"]}).json()
        assert all(p["id"] and p["name"] for p in u["places"])
        c = http.post("/api/check/hours", json={"planId": r["planId"]}).json()
        assert c["ok"] and c["before"] and c["after"] and c["plan"]["planId"] == c["planId"]
        assert all(x["status"] in ("hours found", "no hours", "closed", "not found") for x in c["results"])
        assert http.post("/api/check/hours", json={"planId": "nope"}).status_code == 404


def test_rescue_ladder(server):
    """Nobody answers: live link + SMS, then call, then backup contact, then the Call 911 button. Never an automatic 911 call."""
    async def run():
        async with httpx.AsyncClient(base_url=server, timeout=60) as http:
            r = (await http.post("/api/walks", json={"origin": POWELL, "destination": CIVIC, "day": 4, "minute": 1380, "walker": "Arya", "guardian": "Maya",
                                                     "backupName": "Sam", "backupPhone": "+14155550199", "replay": True, "timeScale": 60})).json()
        w = await Client.open(server, r["walkId"], "walker", r["walkerToken"])
        data = (await w.wait("walk.plan"))["plan"]["data"]
        await w.send({"type": "walk.accept", "choice": "hootroute"}, r["walkId"]); await w.send({"type": "walk.start", "replay": True}, r["walkId"])
        await w.send({"type": "walk.position", "lngLat": data["stopAt"], "heading": 0, "speed": 0, "progress": 0, "replay": True}, r["walkId"])
        steps = []
        for _ in range(4): steps.append((await w.wait("rescue.ladder", 20))["step"])
        assert steps == [0, 1, 2, 3]
        last = await w.wait("agent.log", 5, where=lambda m: m["text"].startswith("Step 4"))
        assert "does not dial 911" in last["text"]
        await w.ws.close()
    asyncio.run(run())


def test_demo_rooms_still_relay(server):
    async def run():
        a = await Client.open(server, "demo-test", "walker"); b = await Client.open(server, "demo-test", "room")
        await a.ws.send(json.dumps({"id": "x1", "walkId": "demo-test", "ts": 1, "from": "engine", "msg": {"type": "voice.say", "agent": "guide", "text": "hi"}}))
        assert (await b.wait("voice.say", 5))["text"] == "hi"
    asyncio.run(run())


def test_walk_survives_restart(tmp_path):
    """Kill the gateway mid-walk; after it comes back the Checker still asks and the Rescuer still alerts."""
    port = free_port(); base = f"http://127.0.0.1:{port}"
    env = {**os.environ, "DB_PATH": str(tmp_path / "r.db"), "ADMIN_TOKEN": "", "TWILIO_ACCOUNT_SID": "", "CARTESIA_API_KEY": ""}

    def boot():
        p = subprocess.Popen([sys.executable, "-m", "uvicorn", "main:app", "--port", str(port), "--log-level", "warning"], cwd=ROOT / "services" / "api", env=env)
        for _ in range(120):
            try:
                if httpx.get(base + "/api/health", timeout=1).status_code == 200: return p
            except httpx.HTTPError: pass
            time.sleep(0.5)
        p.kill(); raise RuntimeError("no boot")

    async def first_half():
        r = httpx.post(base + "/api/walks", json={"origin": POWELL, "destination": CIVIC, "day": 4, "minute": 1380, "walker": "Arya", "guardian": "Maya",
                                                  "replay": True, "timeScale": 60}, timeout=60).json()
        w = await Client.open(base, r["walkId"], "walker", r["walkerToken"])
        data = (await w.wait("walk.plan"))["plan"]["data"]
        await w.send({"type": "walk.accept", "choice": "hootroute"}, r["walkId"]); await w.send({"type": "walk.start", "replay": True}, r["walkId"])
        await w.wait("voice.say", where=lambda m: m["text"].startswith("Okay"))
        await w.ws.close(); return r, data

    async def second_half(r, data):
        w = await Client.open(base, r["walkId"], "walker", r["walkerToken"])
        assert any(e["msg"]["type"] == "walk.plan" for e in w.got)
        await w.send({"type": "walk.position", "lngLat": data["stopAt"], "heading": 0, "speed": 0, "progress": 0, "replay": True}, r["walkId"])
        await w.wait("checkin.ask", 15); await w.wait("guardian.alert", 15); await w.ws.close()

    p = boot()
    try: r, data = asyncio.run(first_half())
    finally: p.terminate(); p.wait(10)
    p = boot()
    try: asyncio.run(second_half(r, data))
    finally: p.terminate(); p.wait(10)


def test_full_walk_under_uagents(tmp_path):
    """Same walk, but the four agents run as uAgents in live_bureau.py and hand off to each other with uAgents messages."""
    agents_py = ROOT / ".venv-agents" / "bin" / "python"
    if not agents_py.exists(): pytest.skip("no .venv-agents")
    port, bridge, bureau = free_port(), free_port(), free_port(); base = f"http://127.0.0.1:{port}"
    common = {**os.environ, "BRIDGE_SECRET": "test-secret", "TWILIO_ACCOUNT_SID": "", "CARTESIA_API_KEY": ""}
    b = subprocess.Popen([str(agents_py), "live_bureau.py"], cwd=ROOT / "services" / "agents",
                         env={**common, "HOOTROUTE_MODE": "local", "HOOTROUTE_ALLOW_DEV_SEEDS": "1", "GATEWAY_URL": base, "BRIDGE_PORT": str(bridge), "BUREAU_PORT": str(bureau)})
    g = subprocess.Popen([sys.executable, "-m", "uvicorn", "main:app", "--port", str(port), "--log-level", "warning"], cwd=ROOT / "services" / "api",
                         env={**common, "DB_PATH": str(tmp_path / "u.db"), "ADMIN_TOKEN": "", "AGENT_RUNTIME": "uagents", "UAGENTS_BRIDGE_URL": f"http://127.0.0.1:{bridge}", "PUBLIC_URL": base})
    try:
        for url in (base + "/api/health", f"http://127.0.0.1:{bridge}/health"):
            for _ in range(120):
                try:
                    if httpx.get(url, timeout=1).status_code == 200: break
                except httpx.HTTPError: pass
                time.sleep(0.5)
            else: raise RuntimeError(f"{url} did not start")
        assert httpx.get(base + "/api/health").json()["runtime"] == "uagents"
        assert httpx.post(base + "/api/internal/publish", json={"walkId": "x", "msg": {"type": "guardian.alert"}}).status_code == 401
        asyncio.run(_full_walk(base))
    finally:
        for p in (g, b): p.terminate(); p.wait(15)
