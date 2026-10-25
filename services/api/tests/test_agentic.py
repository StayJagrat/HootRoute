"""The agentic layer: approval-gated investigation, evidence provenance, Mission Recovery, guardian sharing, notification
gating, numbers verification, and the security defaults. Unit tests first, then a real gateway process.

    .venv/bin/python -m pytest services/api/tests -q
"""
import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
import websockets

ROOT = Path(__file__).resolve().parents[3]
for p in ("services/agents", "services/api"): sys.path.insert(0, str(ROOT / p))
from test_gateway import CIVIC, POWELL, Client, free_port  # noqa: E402

MOSCONE = {"lat": 37.7842, "lon": -122.4016, "name": "Moscone Center"}
CITY_HALL = {"lat": 37.7793, "lon": -122.4193, "name": "City Hall"}


# ------------------------------------------------------------------------------------------------ units
def test_numbers_check():
    from hootroute_agents.head_brain import numbers_check
    tool = {"recommended": {"score": 77, "minutes": 25.2, "longest_empty_m": 390}, "fastest": {"score": 57, "minutes": 24.1, "longest_empty_m": 560}, "passMinute": 1410}
    ok = numbers_check("Heads up. HootRoute scores 77 vs 57, 25.2 vs 24.1 min (+1.1 min), longest stretch 390 m vs 560 m. You pass it at 11:30 PM.", [tool])
    assert ok["ok"], ok
    bad = numbers_check("HootRoute scores 91 and the stretch is 120 m, leaving at 11:45 PM.", [tool])
    assert not bad["ok"] and {"91", "120"} <= set(bad["unverified"]) and any("11:45" in x for x in bad["unverified"])
    assert numbers_check("2 places have unknown hours.", [tool])["ok"]          # small counts are fine


def test_preferences_pick_from_engine_options():
    from hootroute_agents.preferences import choose_option
    opts = [{"id": "fast", "label": "Fastest", "stats": {"score": 57, "minutes": 20.0, "longestEmptyM": 500}, "turnsPerKm": 6.0, "mainPct": 40, "placesOpen": 3},
            {"id": "balanced", "label": "Balanced", "stats": {"score": 66, "minutes": 21.0, "longestEmptyM": 400}, "turnsPerKm": 2.5, "mainPct": 70, "placesOpen": 5},
            {"id": "best", "label": "HootRoute", "stats": {"score": 77, "minutes": 24.0, "longestEmptyM": 300}, "turnsPerKm": 4.0, "mainPct": 55, "placesOpen": 9}]
    assert choose_option(opts, {"fewerTurns": True})["optionId"] == "balanced"
    assert choose_option(opts, {"fastest": True})["optionId"] == "fast"
    assert choose_option(opts, {"preferOpenPlaces": True})["optionId"] == "best"
    assert choose_option(opts, {"lowDistraction": True}) is None             # guidance setting, not a route choice
    assert "2.5 turns per km" in choose_option(opts, {"fewerTurns": True})["reason"]


def test_contact_gating():
    from hootroute_agents.runtime import Runtime
    from hootroute_agents.walk import Walk

    class FakeNotifier:
        enabled = True; sent: list = []
        async def sms(self, to, body): self.sent.append(to); return "sent"
        async def call(self, to, say): self.sent.append(to); return "placed"

    rt = Runtime(None, None, FakeNotifier()); rt.max_notifications = 2
    w = Walk(id="w", walker="A", guardian="M", guardian_phone="+14155550123", guardian_url="", origin={}, dest={}, day=4, minute=1380)
    run = lambda *a: asyncio.run(rt.contact(w, *a))
    assert run("sms", "+14155550123", "x").startswith("off (walker did not opt in")
    w.notify_consent = True
    assert run("call", "+911", "x") == "refused (emergency number)"
    w.sharing = False; assert run("sms", "+14155550123", "x").startswith("off (walker stopped sharing")
    w.sharing = True; rt.sms_allowlist = {"+14155550199"}
    assert run("sms", "+14155550123", "x").startswith("blocked")
    rt.sms_allowlist = set()
    assert run("sms", "+14155550123", "x") == "sent" and run("call", "+14155550123", "x") == "placed"
    assert run("sms", "+14155550123", "x").startswith("skipped (cap")
    assert FakeNotifier.sent == ["+14155550123", "+14155550123"]


def test_apify_run_records_run_id_and_aborts_on_timeout(monkeypatch):
    from hootroute_agents import hours_check
    monkeypatch.setenv("APIFY_TOKEN", "test-token-not-real")
    places = [{"id": "n1", "name": "Corner Cafe", "lngLat": [-122.41, 37.78]}]
    calls = []

    def ok(req: httpx.Request):
        calls.append((req.method, req.url.path))
        if req.url.path.endswith("/runs"): return httpx.Response(201, json={"data": {"id": "RUN123", "status": "RUNNING", "defaultDatasetId": "DS1"}})
        if req.url.path.endswith("/actor-runs/RUN123"): return httpx.Response(200, json={"data": {"id": "RUN123", "status": "SUCCEEDED", "defaultDatasetId": "DS1"}})
        if req.url.path.endswith("/datasets/DS1/items"): return httpx.Response(200, json=[{"title": "Corner Cafe", "location": {"lat": 37.78, "lng": -122.41}}])
        return httpx.Response(404)
    items, info = hours_check.run_actor(places, client=httpx.Client(transport=httpx.MockTransport(ok)))
    assert info["runId"] == "RUN123" and info["consoleUrl"].endswith("/RUN123") and len(items) == 1 and info["status"] == "SUCCEEDED"

    def stuck(req: httpx.Request):
        calls.append((req.method, req.url.path))
        if req.url.path.endswith("/abort"): return httpx.Response(200, json={"data": {}})
        return httpx.Response(201, json={"data": {"id": "RUN9", "status": "RUNNING", "defaultDatasetId": "DS9"}})
    with pytest.raises(TimeoutError):
        hours_check.run_actor(places, timeout_s=0, client=httpx.Client(transport=httpx.MockTransport(stuck)))
    assert ("POST", "/v2/actor-runs/RUN9/abort") in calls


def test_evidence_shape_never_confirms_staffing():
    from hootroute_agents.evidence import from_result, reusable
    ev = from_result({"id": "n1", "name": "Cafe", "status": "hours found", "hours": "Mo-Su 07:00-23:00", "source": "https://maps.google.com/?cid=1",
                      "checkedAt": "2026-10-24T19:00:00+0000", "confidence": 0.9}, {"actor": "compass/crawler-google-places", "runId": "R1"}, False)
    assert ev["kind"] == "published_hours" and ev["confirmedOpenNow"] is False and ev["source"]["runId"] == "R1" and "not confirmation" in ev["note"]
    nf = from_result({"id": "n2", "name": "X", "status": "not found", "hours": None, "source": None, "checkedAt": None}, None, False)
    assert nf["kind"] == "not_found" and nf["hours"] is None
    assert not reusable({"kind": "check_failed", "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")})
    assert reusable({"kind": "not_found", "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")})


def test_security_helpers(monkeypatch):
    from hootroute_api.security import DailyBudget, RateLimiter, redact
    assert redact("GET /ws?walk=abc&role=walker&token=SECRET123 HTTP/1.1") == "GET /ws?walk=abc&role=walker&token=*** HTTP/1.1"
    assert "SECRETG" not in redact("/guardian/abc?g=SECRETG")
    lim = RateLimiter({"check": (2, 60)}); assert lim.take("check", "a") == 0 and lim.take("check", "a") == 0 and lim.take("check", "a") > 0 and lim.take("check", "b") == 0
    b = DailyBudget(1); assert b.spend() and not b.spend() and b.remaining() == 0
    from hootroute_api import settings as st
    for k, v in {"HOOTROUTE_ENV": "production", "ADMIN_TOKEN": "", "PUBLIC_URL": "http://x", "CORS_ORIGINS": "*", "AGENT_RUNTIME": "uagents", "BRIDGE_SECRET": ""}.items():
        monkeypatch.setenv(k, v)
    probs = " ".join(st.Settings().problems())
    assert "BRIDGE_SECRET" in probs and "ADMIN_TOKEN" in probs and "https" in probs and "CORS" in probs


# ------------------------------------------------------------------------------------------------ a real gateway
@pytest.fixture(scope="module")
def gw(tmp_path_factory):
    port = free_port(); d = tmp_path_factory.mktemp("agentic")
    env = {**os.environ, "DB_PATH": str(d / "a.db"), "ADMIN_TOKEN": "", "TWILIO_ACCOUNT_SID": "", "CARTESIA_API_KEY": "", "PUBLIC_URL": f"http://127.0.0.1:{port}",
           "ANTHROPIC_API_KEY": "", "APIFY_TOKEN": "", "HOURS_CHECK_MOCK": "1", "HOURS_LIVE_FILE": str(d / "hours_live.json"), "RATE_LIMITS": "0"}
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


def test_open_in_text_never_starts_a_paid_check(gw):
    r = httpx.post(gw + "/api/head/ask", json={"text": "from Moscone Center to City Hall at 11:30 pm, somewhere open on the way, fewer turns"}, timeout=120).json()
    tools = [t["tool"] for t in r["trace"]]
    assert "check_listed_hours" not in tools and "propose_hours_check" not in tools and not r.get("pendingApproval"), tools
    assert r["preferences"]["preferOpenPlaces"] and r["preferences"]["fewerTurns"] and "rank_by_preferences" in tools
    assert all(t["persona"] and t["why"] and t["status"] in ("ok", "error") for t in r["trace"])
    assert r["numbersCheck"]["ok"] and r["planId"] and r["plan"]["planId"] == r["planId"]


def test_approval_gate_then_evidence_and_rescore(gw):
    with httpx.Client(base_url=gw, timeout=120) as http:
        r = http.post("/api/head/ask", json={"text": "from Moscone Center to City Hall at 11:30 pm and check listed hours"}).json()
        ap = r.get("pendingApproval")
        if not ap: pytest.skip("no unknown-hours places on this route")
        assert ap["provider"] == "mock" and ap["maxUsd"] == 0.5 and ap["places"]
        assert "check_listed_hours" not in [t["tool"] for t in r["trace"]] and any(t["status"] == "needs_approval" for t in r["trace"])
        assert http.post("/api/head/approve", json={"session": r["session"], "approvalId": "nope", "approve": True}).status_code == 404
        a = http.post("/api/head/approve", json={"session": r["session"], "approvalId": ap["id"], "approve": True}).json()
        checked = [t for t in a["trace"] if t["tool"] == "check_listed_hours"]
        assert checked and checked[0]["why"].startswith("The walker approved")
        assert {e["placeId"] for e in a["evidence"]} == {p["id"] for p in ap["places"]}, "exactly the approved places"
        assert all(e["confirmedOpenNow"] is False and e["source"]["provider"] == "mock" for e in a["evidence"])
        assert a["before"] and a["after"] and a["numbersCheck"]["ok"] and a["planId"]
        assert http.post("/api/head/approve", json={"session": r["session"], "approvalId": ap["id"], "approve": True}).status_code == 404, "single use"
        ev = http.get(f"/api/plans/{a['planId']}/evidence").json()
        assert ev["places"] and set(ev["counts"]) == {"listed", "live", "shopkeeper", "unknown", "stale"}
        assert all(p["openAtPass"] is None for p in ev["places"] if p["hours"] is None), "unknown stays unknown"
        kinds = {p["evidence"]["kind"] for p in ev["places"]}; assert kinds <= {"osm_tag", "listing_batch", "listing_live", "shopkeeper", "none"}


def test_declined_approval_checks_nothing(gw):
    with httpx.Client(base_url=gw, timeout=120) as http:
        r = http.post("/api/head/ask", json={"text": "from Powell St BART to Civic Center BART at 11 pm, check hours"}).json()
        if not r.get("pendingApproval"): pytest.skip("no unknown-hours places on this route")
        a = http.post("/api/head/approve", json={"session": r["session"], "approvalId": r["pendingApproval"]["id"], "approve": False}).json()
        assert "didn't check anything" in a["answer"] and not a.get("evidence") and a["trace"][0]["status"] == "skipped"


def test_preferences_on_plans(gw):
    p = httpx.post(gw + "/api/plans", json={"origin": MOSCONE, "destination": CITY_HALL, "day": 4, "minute": 1410, "preferences": {"fewerTurns": True}}, timeout=60).json()
    assert p["preferenceChoice"]["optionId"] in {o["id"] for o in p["options"]} and "turns per km" in p["preferenceChoice"]["reason"]
    assert all("turnsPerKm" in o and "avoidsReport" in o for o in p["options"])


def test_guardian_sharing_and_recovery(gw):
    async def run():
        async with httpx.AsyncClient(base_url=gw, timeout=60) as http:
            w = (await http.post("/api/walks", json={"origin": POWELL, "destination": CIVIC, "day": 4, "minute": 1380, "walker": "Arya", "guardian": "Maya",
                                                     "guardianPhone": "+14155550123", "replay": True, "timeScale": 60})).json()
            wid, token = w["walkId"], w["walkerToken"]; g = w["guardianUrl"].split("?g=")[1]
            assert w["sms"] is False, "no opt-in, no SMS"
            # guardian needs its own token; the walk id alone is not enough
            with pytest.raises(Exception):
                s = await websockets.connect(f"{gw.replace('http', 'ws')}/ws?walk={wid}&role=guardian&token="); await s.recv(); await s.recv()
            walker = await Client.open(gw, wid, "walker", token); guardian = await Client.open(gw, wid, "guardian", g)
            data = (await walker.wait("walk.plan"))["plan"]["data"]
            assert (await http.get(f"/api/walks/{wid}", params={"g": g})).status_code == 200
            # Mission Recovery: report a block ahead, get options, nothing switches until the walker chooses
            await walker.send({"type": "walk.accept", "choice": "hootroute"}, wid); await walker.send({"type": "walk.start", "replay": True}, wid)
            await walker.send({"type": "walk.position", "lngLat": data["route"][1], "heading": 0, "speed": 1.3, "progress": 0, "replay": True}, wid)
            await walker.send({"type": "obstacle.report", "kind": "construction", "note": "fenced sidewalk"}, wid)
            rec = await walker.wait("recovery.options", 30)
            assert rec["current"]["id"] == "keep" and rec["options"] and rec["explanation"] and rec["explainedBy"]
            assert all(o["id"] in ("fast", "balanced", "best") and o["stats"]["minutes"] > 0 for o in rec["options"])
            await walker.wait("agent.log", where=lambda m: m["agent"] == "rescuer" and "Report received" in m["text"])
            pick = next((o for o in rec["options"] if o["avoidsReport"]), rec["options"][0])
            await walker.send({"type": "recovery.choose", "recoveryId": rec["recoveryId"], "optionId": pick["id"]}, wid)
            plan = await walker.wait("walk.plan", 20, where=lambda m: m["plan"]["reason"].startswith("Switched after your report"))
            assert plan["plan"]["data"]["route"] == pick["coords"], "the chosen option becomes the drawn route"
            await walker.send({"type": "recovery.choose", "recoveryId": rec["recoveryId"], "optionId": "best"}, wid)
            await walker.wait("agent.log", where=lambda m: "expired" in m["text"])
            # stop sharing: guardian is cut off and the old link is dead
            assert (await http.post(f"/api/walks/{wid}/share", json={"active": False})).status_code == 404, "only the walker can"
            r = (await http.post(f"/api/walks/{wid}/share", json={"active": False}, headers={"X-Walker-Token": token})).json()
            assert r == {"active": False, "guardianUrl": None}
            await walker.wait("share.update", where=lambda m: m["active"] is False)
            with pytest.raises(Exception):
                for _ in range(50): await asyncio.wait_for(guardian.ws.recv(), 5)
            with pytest.raises(Exception):
                s = await websockets.connect(f"{gw.replace('http', 'ws')}/ws?walk={wid}&role=guardian&token={g}"); await s.recv(); await s.recv()
            assert (await http.get(f"/api/walks/{wid}", params={"g": g})).status_code == 404
            r2 = (await http.post(f"/api/walks/{wid}/share", json={"active": True}, headers={"X-Walker-Token": token})).json()
            assert r2["active"] and r2["guardianUrl"] and g not in r2["guardianUrl"], "a new link, never the old one"
            await walker.ws.close()
    asyncio.run(run())


def test_check_hours_needs_confirm_and_bridge_is_closed(gw):
    p = httpx.post(gw + "/api/plans", json={"origin": POWELL, "destination": CIVIC, "day": 4, "minute": 1380}, timeout=60).json()
    assert httpx.post(gw + "/api/check/hours", json={"planId": p["planId"]}).status_code == 428
    c = httpx.post(gw + "/api/check/hours", json={"planId": p["planId"], "confirm": True}, timeout=60).json()
    assert "evidence" in c and "reused" in c and c["mock"]
    assert httpx.post(gw + "/api/internal/publish", json={"walkId": "x", "msg": {"type": "guardian.alert"}}).status_code == 401
    h = httpx.get(gw + "/api/health").json(); assert h["apifyMock"] and "apifyRunsLeft" in h
    a = httpx.get(gw + "/api/agents").json(); assert [x["persona"] for x in a] == ["Professor Hoot", "Scoot McRoute", "Sherlock Hoots", "Wingman Wally"]


def test_claude_path_with_scripted_model(monkeypatch):
    """No API key in CI: script Claude's turns. Read-only calls in one turn run concurrently; a final answer with a number
    no tool produced is replaced by the engine summary; a truthful one is kept."""
    from hootroute_agents import head_brain
    from hootroute_agents.engine_port import EnginePort
    from hootroute_engine.engine import Engine
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-not-a-real-key")
    eng = Engine(); brain = head_brain.HeadBrain(EnginePort(eng), eng)
    o = {"name": "Moscone Center", "lat": 37.7842, "lon": -122.4016}; d = {"name": "City Hall", "lat": 37.7793, "lon": -122.4193}
    final = {"text": ""}

    def script():
        yield {"stop_reason": "tool_use", "content": [{"type": "text", "text": "Finding both places."},
               {"type": "tool_use", "id": "a", "name": "find_place", "input": {"query": "Moscone Center", "why": "resolve start"}},
               {"type": "tool_use", "id": "b", "name": "find_place", "input": {"query": "City Hall", "why": "resolve destination"}}]}
        yield {"stop_reason": "tool_use", "content": [{"type": "tool_use", "id": "c", "name": "plan_routes", "input": {"origin": o, "destination": d, "day": 4, "minute": 1410, "why": "score routes"}}]}
        yield {"stop_reason": "end_turn", "content": [{"type": "text", "text": final["text"]}]}

    async def fake_claude(msgs, system, tools=None, **kw):
        return next(state["it"])
    state = {}; monkeypatch.setattr(head_brain, "claude", fake_claude)

    final["text"] = "Good to go. The HootRoute route scores 431 and saves 214 minutes."; state["it"] = script()
    r = asyncio.run(brain.ask("from Moscone Center to City Hall at 11:30 pm"))
    groups = [t.get("group") for t in r["trace"] if t["tool"] == "find_place"]
    assert groups[0] is not None and groups[0] == groups[1], "independent lookups ran concurrently"
    assert [t["why"] for t in r["trace"]][:2] == ["resolve start", "resolve destination"]
    assert not r["numbersCheck"]["ok"] and {"431", "214"} <= set(r["numbersCheck"]["unverified"]) and "replaced" in r["by"]
    st = r["plan"]["stats"]; assert str(st["hootroute"]["score"]) in r["answer"]

    final["text"] = f"Good to go. The HootRoute route scores {st['hootroute']['score']} versus {st['shortest']['score']}, {st['hootroute']['minutes']} min. Conditions, not a safety rating."
    state["it"] = script()
    r2 = asyncio.run(brain.ask("from Moscone Center to City Hall at 11:30 pm"))
    assert r2["numbersCheck"]["ok"] and r2["answer"] == final["text"] and r2["by"].startswith("Claude")


def test_allow_checks_is_ignored_for_the_public(gw):
    r = httpx.post(gw + "/api/head/ask", json={"text": "from Moscone Center to City Hall at 11:30 pm, check listed hours", "allowChecks": True}, timeout=120).json()
    assert "check_listed_hours" not in [t["tool"] for t in r["trace"]], "only the control room may skip the approval card"


def test_stale_recovery_choice_is_closed(gw):
    async def run():
        async with httpx.AsyncClient(base_url=gw, timeout=60) as http:
            w = (await http.post("/api/walks", json={"origin": POWELL, "destination": CIVIC, "day": 4, "minute": 1380, "walker": "Arya", "guardian": "Maya", "replay": True, "timeScale": 60})).json()
        c = await Client.open(gw, w["walkId"], "walker", w["walkerToken"]); await c.wait("walk.plan")
        await c.send({"type": "recovery.choose", "recoveryId": "old", "optionId": "best"}, w["walkId"])
        assert (await c.wait("recovery.closed", 10))["recoveryId"] == "old"
        await c.ws.close()
    asyncio.run(run())


def test_backend_route_limits_and_reviewed_walk(gw):
    """Optional API limits apply without changing the frontend or the reviewed-plan handoff."""
    request = {"origin": MOSCONE, "destination": CITY_HALL, "day": 4, "minute": 1410, "maxExtraMinutes": 0}
    response = httpx.post(gw + "/api/plans", json=request, timeout=120)
    assert response.status_code == 200, response.text
    plan = response.json()
    assert plan["recommended"] == "fast" and plan["routingLimits"] == {"maxExtraMinutes": 0}
    assert plan["evidenceCoverage"]["confirmedStaffing"] is False
    bad = httpx.post(gw + "/api/plans", json={**request, "maxGapM": 0}, timeout=120)
    assert bad.status_code == 422 and "No candidate" in bad.json()["detail"]

    async def run():
        async with httpx.AsyncClient(base_url=gw, timeout=120) as client:
            response = await client.post("/api/walks", json={**request, "planId": plan["planId"], "guardian": "Contact", "replay": True})
            assert response.status_code == 201
            walk = response.json()
        walker = await Client.open(gw, walk["walkId"], "walker", walk["walkerToken"])
        try:
            reviewed = (await walker.wait("walk.plan", 30))["plan"]["data"]
            assert reviewed["route"] == plan["route"] and reviewed["routingLimits"] == plan["routingLimits"]
            await walker.send({"type": "walk.end", "outcome": "ended", "summary": "Test complete."}, walk["walkId"])
        finally: await walker.ws.close()
    asyncio.run(run())


@pytest.mark.parametrize("mode", ["cycle", "wheelchair"])
def test_travel_profile_plan_evidence_and_live_recovery(gw, mode):
    request = {"origin": MOSCONE, "destination": CITY_HALL, "day": 4, "minute": 1410, "travelMode": mode}
    response = httpx.post(gw + "/api/plans", json=request, timeout=120)
    assert response.status_code == 200, response.text
    plan = response.json()
    assert plan["travelMode"] == mode and plan["travelProfile"]["speedMps"] != 1.35
    assert all(o["modeConditions"] is not None for o in plan["options"])
    assert httpx.post(gw + "/api/check/route", json={"planId": plan["planId"]}, timeout=60).status_code == 200
    evidence = httpx.get(gw + f"/api/plans/{plan['planId']}/evidence", timeout=60).json()
    assert "places" in evidence

    async def run():
        async with httpx.AsyncClient(base_url=gw, timeout=120) as http:
            response = await http.post("/api/walks", json={**request, "planId": plan["planId"], "guardian": "Contact", "replay": True, "timeScale": 60})
            assert response.status_code == 201, response.text
            journey = response.json()
            saved = (await http.get(f"/api/walks/{journey['walkId']}", headers={"X-Walker-Token": journey["walkerToken"]})).json()
            assert saved["travel_mode"] == mode
        walker = await Client.open(gw, journey["walkId"], "walker", journey["walkerToken"])
        try:
            data = (await walker.wait("walk.plan", 30))["plan"]["data"]
            assert data["travelMode"] == mode and data["route"] == plan["route"]
            await walker.send({"type": "walk.accept", "choice": "hootroute"}, journey["walkId"])
            await walker.send({"type": "walk.start", "replay": True}, journey["walkId"])
            await walker.send({"type": "walk.position", "lngLat": data["route"][1], "heading": 0, "speed": data["travelProfile"]["speedMps"], "progress": 0, "replay": True}, journey["walkId"])
            await walker.send({"type": "obstacle.report", "kind": "construction"}, journey["walkId"])
            recovery = await walker.wait("recovery.options", 45)
            option = recovery["options"][0]["id"]
            await walker.send({"type": "recovery.choose", "recoveryId": recovery["recoveryId"], "optionId": option}, journey["walkId"])
            updated = (await walker.wait("walk.plan", 20, where=lambda m: "Switched after" in m["plan"]["reason"]))["plan"]["data"]
            assert updated["travelMode"] == mode and updated["travelProfile"]["speedMps"] == data["travelProfile"]["speedMps"]
            await walker.send({"type": "walk.end", "outcome": "ended", "summary": "Test complete."}, journey["walkId"])
        finally: await walker.ws.close()
    asyncio.run(run())


def test_head_preserves_selected_profile_and_pace(gw):
    response = httpx.post(gw + "/api/head/ask", json={"text": "from Moscone Center to City Hall Friday at 11:30 PM", "travelMode": "cycle", "travelOptions": {"speedKmh": 20}}, timeout=120)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["plan"]["travelMode"] == "cycle" and result["plan"]["travelOptions"]["speedKmh"] == 20
    followup = httpx.post(gw + "/api/head/ask", json={"text": "fewer turns", "session": result["session"], "travelMode": "wheelchair"}, timeout=120).json()
    assert followup["plan"]["travelMode"] == "wheelchair"
