"""HootRoute gateway: REST for planning and walk creation, one WebSocket room per walk, and the host for the agents.

    cd services/api && ../../.venv/bin/uvicorn main:app --port 8000

The gateway relays and persists. Walk logic (planning, check-ins, alerts, arrival, audits) lives in the agents
(services/agents/hootroute_agents), which run in-process here or under uAgents (AGENT_RUNTIME=uagents).
"""
from __future__ import annotations

import asyncio
import logging
import secrets
import sys
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from .settings import ROOT, settings

sys.path.insert(0, str(ROOT / "services" / "engine"))
sys.path.insert(0, str(ROOT / "services" / "agents"))

from hootroute_agents import evidence as evidence_mod, hours_check, inspect_route  # noqa: E402
from hootroute_agents.brand import PERSONAS  # noqa: E402
from hootroute_agents.preferences import Preferences, choose_option  # noqa: E402
from hootroute_agents.engine_port import EnginePort  # noqa: E402
from hootroute_agents.head_brain import HeadBrain, enabled as claude_enabled  # noqa: E402
from hootroute_agents.notify import E164, Notifier  # noqa: E402
from hootroute_agents.plan_data import build_demo_data, build_route_data  # noqa: E402
from hootroute_agents.runtime import Runtime  # noqa: E402
from hootroute_engine import geo  # noqa: E402
from hootroute_engine.engine import Engine  # noqa: E402

from . import vision, voice  # noqa: E402
from .security import DailyBudget, RateLimiter, install_log_redaction, limit  # noqa: E402
from .agent_bridge import RemoteRuntime  # noqa: E402
from .contract import AGENT_TYPES, ROLES, clean_client_msg, envelope  # noqa: E402
from .db import DB  # noqa: E402
from .rooms import Hub  # noqa: E402

log = logging.getLogger("hootroute.gateway")
SF = ZoneInfo("America/Los_Angeles")
VERSION = "1.1.0"
install_log_redaction()


def sf_now() -> tuple[int, int]:
    n = datetime.now(SF); return n.weekday(), n.hour * 60 + n.minute


# ------------------------------------------------------------------------------------------------ plan cache
class Plans:
    """Plans shown in the planner, kept briefly so the walk starts on exactly the route the walker reviewed."""
    def __init__(self, ttl: int): self.ttl = ttl; self.items: dict[str, tuple[float, tuple, dict, dict]] = {}

    def put(self, key: tuple, data: dict, routes: dict) -> str:
        now = time.time(); self.items = {k: v for k, v in self.items.items() if now - v[0] < self.ttl}
        pid = uuid.uuid4().hex[:16]; self.items[pid] = (now, key, data, routes); return pid

    def get(self, pid: str | None, key: tuple) -> tuple[dict, dict] | None:
        v = self.items.get(pid or "")
        return (v[2], v[3]) if v and v[1] == key and time.time() - v[0] < self.ttl else None


def plan_key(o, d, day, minute) -> tuple:
    g = lambda p, k: p[k] if isinstance(p, dict) else getattr(p, k)
    return (round(g(o, "lat"), 5), round(g(o, "lon"), 5), round(g(d, "lat"), 5), round(g(d, "lon"), 5), day, minute)


# ------------------------------------------------------------------------------------------------ lifespan
@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    install_log_redaction()
    problems = settings.problems()
    for p in problems: log.error("configuration: %s", p)
    if problems and (settings.production or settings.agent_runtime == "uagents"):
        raise RuntimeError("refusing to start with insecure configuration: " + "; ".join(problems))
    db = DB(settings.db_path); hub = Hub(db)
    engine: Engine = await run_in_threadpool(Engine)
    live = hours_check.load_live(engine)
    if live: log.info("re-applied %d hours found by earlier live checks", live)
    port = EnginePort(engine); notifier = Notifier(settings.twilio_sid, settings.twilio_token, settings.twilio_from)

    async def agent_send(walk_id: str, msg: dict): await hub.publish(envelope(walk_id, msg, "engine"))

    runtime = RemoteRuntime(settings.uagents_bridge_url, settings.bridge_secret) if settings.agent_runtime == "uagents" else Runtime(port, agent_send, notifier)
    budget = DailyBudget(settings.apify_daily_runs)
    for k, v in dict(db=db, hub=hub, engine=engine, port=port, runtime=runtime, plans=Plans(settings.plan_ttl_s), head=HeadBrain(port, engine, budget),
                     limiter=RateLimiter(enabled=settings.rate_limits), budget=budget).items(): setattr(app.state, k, v)
    apply_declarations(app)
    hub.observe(lambda env: on_envelope(app, env))
    for rec in db.walks(active_only=True, limit=50):                 # resume walks that were running before a restart
        if runtime.restore(rec, guardian_url(None, rec["id"], rec.get("guardian_token")), db.envelopes(rec["id"]), db.routes(rec["id"])):
            log.info("resumed walk %s (%s)", rec["id"], rec["status"])
        elif rec["status"] != "ended" and time.time() - rec["created_at"] > 6 * 3600:
            db.update_walk(rec["id"], status="ended", ended_at=time.time(), outcome="expired")
    runtime.start()
    tasks = [asyncio.create_task(nightly(app)), asyncio.create_task(housekeeping(app))]
    log.info("gateway ready: engine %.1fs, %d segments, runtime=%s, sms=%s, tts=%s", engine.boot_seconds, engine.W.G.number_of_edges(),
             settings.agent_runtime, settings.sms_enabled, settings.tts_enabled)
    yield
    for t in tasks: t.cancel()
    await runtime.stop()


app = FastAPI(title="HootRoute", version=VERSION, lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins), allow_methods=["*"], allow_headers=["*"])

def _limited(bucket: str):
    def dep(request: Request): limit(request, bucket)
    return Depends(dep)


app.include_router(vision.router, dependencies=[_limited("vision")]); app.include_router(voice.router, dependencies=[_limited("tts")])


def apply_declarations(app: FastAPI):
    """Shopkeeper declarations are 'tonight' facts: they apply to every walk planned before they expire."""
    overrides = {d["place_id"]: d["until_minute"] for d in app.state.db.declarations() if d["until_minute"]}
    declared = {day: overrides for day in range(7)}
    app.state.engine.set_declarations(declared)
    if isinstance(app.state.runtime, RemoteRuntime): asyncio.get_running_loop().create_task(app.state.runtime.set_declarations(declared))


def guardian_url(request: Request | None, walk_id: str, token: str | None) -> str | None:
    """The guardian's live link. It carries its own token: the walk id alone grants nothing. None while sharing is off."""
    if not token: return None
    base = settings.public_url or (request.headers.get("origin") if request else "") or (str(request.base_url).rstrip("/") if request else "")
    return f"{base}/guardian/{walk_id}?g={token}"


async def on_envelope(app: FastAPI, env: dict):
    """Side effects of the message stream: walk status in the database, alerts, audits; client messages go to the agents."""
    db: DB = app.state.db; rt: Runtime = app.state.runtime; kind = env["msg"]["type"]; wid = env["walkId"]
    if env["from"] != "engine":
        if db.walk(wid) or kind == "audit.run": await rt.handle(env)
        if kind == "guardian.ack": db.ack_alert(wid, env["msg"]["by"])
        elif kind == "walk.start" and env["from"] == "walker": db.update_walk(wid, status="walking", started_at=time.time())
        return
    rec = db.walk(wid)
    if kind == "walk.plan" and rec:
        w = rt.walks.get(wid)
        if w and w.routes: db.set_routes(wid, w.routes)
        if rec["status"] == "planning": db.update_walk(wid, status="planned")
    elif kind == "checkin.ask" and rec: db.update_walk(wid, status="checkin")
    elif kind == "guardian.alert" and rec:
        db.update_walk(wid, status="escalated"); db.add_alert(wid, env["msg"]["reason"], env["msg"]["lngLat"], env["msg"]["where"])
    elif kind == "walk.end" and rec:
        db.update_walk(wid, status="ended", ended_at=time.time(), outcome=env["msg"]["outcome"], summary=env["msg"]["summary"])
    elif kind == "audit.result":
        db.add_audit({k: v for k, v in env["msg"].items() if k != "type"})


async def nightly(app: FastAPI):
    """The Head's overnight audit at 2:00 AM San Francisco time, every night."""
    while True:
        now = datetime.now(SF); nxt = now.replace(hour=2, minute=0, second=0, microsecond=0)
        if nxt <= now: nxt += timedelta(days=1)
        await asyncio.sleep((nxt - now).total_seconds())
        try:
            day = (nxt - timedelta(days=1)).weekday(); res = await app.state.runtime.audit(day, 23 * 60)
            app.state.db.add_audit({k: v for k, v in res.items() if k != "type"}); log.info("nightly audit stored")
        except Exception: log.exception("nightly audit failed")


def expire_stale(app: FastAPI) -> int:
    """Walks nobody finished: demo replays after an hour, real walks after six. Keeps the control room from attaching to them."""
    now = time.time(); n = 0
    for rec in app.state.db.walks(active_only=True, limit=200):
        if now - rec["created_at"] > (3600 if rec["replay"] else 6 * 3600):
            app.state.db.update_walk(rec["id"], status="ended", ended_at=now, outcome="expired"); n += 1
            w = getattr(app.state.runtime, "walks", {}).get(rec["id"])
            if w: w.status = "ended"
    return n


async def housekeeping(app: FastAPI):
    while True:
        await asyncio.sleep(600)
        if expire_stale(app): log.info("expired abandoned walks")
        n = app.state.db.purge_positions(settings.position_retention_h * 3600)
        if n: log.info("purged %d GPS fixes from ended walks", n)
        apply_declarations(app)          # drop expired shop declarations


# ------------------------------------------------------------------------------------------------ models
class Point(BaseModel):
    lat: float = Field(ge=37.6, le=37.9); lon: float = Field(ge=-122.6, le=-122.3); name: str = Field("", max_length=100)


class PlanReq(BaseModel):
    origin: Point; destination: Point
    day: int | None = Field(None, ge=0, le=6); minute: int | None = Field(None, ge=0, le=1439)
    preferences: Preferences | None = None


class WalkReq(PlanReq):
    planId: str | None = None
    choice: str = Field("hootroute", pattern="^(hootroute|usual|balanced)$")
    walker: str = Field("Walker", min_length=1, max_length=40)
    guardian: str = Field(min_length=1, max_length=60)
    guardianPhone: str | None = None
    backupName: str | None = Field(None, max_length=60)
    backupPhone: str | None = None
    thresholds: dict | None = None
    replay: bool = False
    timeScale: float = Field(1.0, ge=1, le=60)
    notifyConsent: bool = False          # the walker opted in to SMS / calls to their contacts; without it only the live link is used

    @field_validator("guardianPhone", "backupPhone")
    @classmethod
    def phone(cls, v):
        if not v: return None
        v = "".join(ch for ch in v if ch.isdigit() or ch == "+")
        if len(v) == 10 and not v.startswith("+"): v = "+1" + v          # US number typed without a country code
        if not E164.match(v): raise ValueError("Use an international number, for example +14155550123.")
        return v


class Declaration(BaseModel):
    openUntil: str = Field(pattern=r"^(closed|24h|([01]\d|2[0-3]):[0-5]\d)$"); safeHaven: bool = False; frontLight: bool = False


def _when(req: PlanReq) -> tuple[int, int]:
    d, m = sf_now()
    return (req.day if req.day is not None else d), (req.minute if req.minute is not None else m)


# ------------------------------------------------------------------------------------------------ REST
@app.get("/api/health")
async def health(request: Request):
    s = request.app.state
    return dict(ok=True, version=VERSION, engine=dict(boot_seconds=s.engine.boot_seconds, segments=s.engine.W.G.number_of_edges()), runtime=settings.agent_runtime,
                walks_active=len(s.db.walks(active_only=True, limit=100)), sms=settings.sms_enabled, tts="cartesia" if settings.tts_enabled else "device",
                claude=claude_enabled(), apify=bool(settings.apify_token) or hours_check.mock_mode(), apifyMock=hours_check.mock_mode(),
                apifyRunsLeft=s.budget.remaining(), production=settings.production, rateLimits=settings.rate_limits)


@app.get("/api/agents")
async def agents():
    """The four personas the UI shows, with what actually runs each one."""
    live = {"head": claude_enabled(), "guide": True, "checker": bool(settings.apify_token) or hours_check.mock_mode(), "rescuer": True}
    return [{**p, "live": live[p["id"]]} for p in PERSONAS]


@app.get("/api/meta")
async def meta(request: Request): return request.app.state.engine.meta()


@app.get("/api/search")
async def search(request: Request, q: str, limit: int = 8):
    return await run_in_threadpool(request.app.state.engine.search, q, min(limit, 20))


@app.post("/api/plans")
async def create_plan(req: PlanReq, request: Request):
    """Score Fastest vs HootRoute for any two points in San Francisco. Returns DemoData plus a planId to start the walk on."""
    limit(request, "plan"); s = request.app.state; day, minute = _when(req)
    try:
        data, routes = await s.port.plan(req.origin.model_dump(), req.destination.model_dump(), day, minute, "Walker", "Guardian")
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    choice = choose_option(data.get("options") or [], req.preferences) if req.preferences else None
    return {"planId": s.plans.put(plan_key(req.origin, req.destination, day, minute), data, routes), **data, "preferenceChoice": choice}


@app.get("/api/route-demo")
async def route_demo(request: Request, lat: float, lon: float, name: str = "Destination", olat: float | None = None, olon: float | None = None,
                     oname: str = "Start", day: int = 4, minute: int = 23 * 60 + 4):
    """Older planner contract (GET). Kept for cached clients; new clients POST /api/plans."""
    if not (0 <= day <= 6 and 0 <= minute < 1440): raise HTTPException(422, "day must be 0-6 and minute 0-1439")
    origin = (olat, olon) if olat is not None and olon is not None else None
    try: return await run_in_threadpool(build_route_data, request.app.state.engine, lat, lon, name, origin, oname if origin else None, day, minute)
    except ValueError as e: raise HTTPException(422, str(e)) from e


@app.get("/api/demo")
async def demo(request: Request):
    """The offline demo corridor (same as web/public/data/demo-route.json)."""
    return await run_in_threadpool(build_demo_data, request.app.state.engine)


@app.post("/api/walks", status_code=201)
async def create_walk(req: WalkReq, request: Request):
    """Start a walk: unique id, a walker token for the walker's phone, and the guardian's live link. The Guide plans it in the room."""
    limit(request, "walk"); s = request.app.state; day, minute = _when(req)
    wid = secrets.token_urlsafe(12).replace("-", "a").replace("_", "b"); token = secrets.token_urlsafe(24); gtoken = secrets.token_urlsafe(18)
    rec = dict(id=wid, created_at=time.time(), status="planning", walker_token=token, walker_name=req.walker.strip(), guardian_name=req.guardian.strip(),
               guardian_phone=req.guardianPhone, origin=req.origin.model_dump(), destination=req.destination.model_dump(), depart_day=day, depart_minute=minute,
               choice=req.choice, thresholds=req.thresholds or {}, replay=req.replay, time_scale=req.timeScale if req.replay else 1.0,
               started_at=None, ended_at=None, outcome=None, summary=None, backup_name=(req.backupName or "").strip() or None, backup_phone=req.backupPhone,
               guardian_token=gtoken, notify_consent=req.notifyConsent, sharing=True)
    s.db.create_walk(rec); s.hub.room(wid, persistent=True)
    gurl = guardian_url(request, wid, gtoken)
    cached = s.plans.get(req.planId, plan_key(req.origin, req.destination, day, minute))
    if cached:      # the plan was made for placeholder names; put the real ones in
        data, routes = cached; data = {**data, "walker": {"id": "walker", "name": rec["walker_name"]},
                                       "guardian": {**data["guardian"], "name": rec["guardian_name"], "initials": "".join(p[0] for p in rec["guardian_name"].split()[:2]).upper()}}
        cached = (data, routes)
    asyncio.create_task(s.runtime.request(rec, gurl, cached))
    return dict(walkId=wid, walkerToken=token, guardianUrl=gurl, walkPath=f"/walk?walk={wid}", sharing=True,
                sms=settings.sms_enabled and req.notifyConsent and bool(req.guardianPhone or req.backupPhone))


def _public(rec: dict) -> dict:
    return {k: rec[k] for k in ("id", "status", "walker_name", "guardian_name", "origin", "destination", "depart_day", "depart_minute", "choice", "replay",
                                "time_scale", "created_at", "started_at", "ended_at", "outcome", "summary", "sharing")}


def walk_role(rec: dict, request: Request) -> str | None:
    """Who is asking about this walk: the walker (X-Walker-Token), the guardian (?g= or X-Guardian-Token), the control room, or nobody."""
    wt = request.headers.get("x-walker-token", ""); gt = request.headers.get("x-guardian-token", "") or request.query_params.get("g", "")
    if wt and secrets.compare_digest(wt, rec["walker_token"]): return "walker"
    if gt and rec.get("guardian_token") and rec.get("sharing") and secrets.compare_digest(gt, rec["guardian_token"]): return "guardian"
    if settings.admin_token and secrets.compare_digest(request.headers.get("x-admin-token", ""), settings.admin_token): return "room"
    return None


@app.get("/api/walks")
async def list_walks(request: Request, active: bool = False, limit: int = 20):
    require_admin(request); return [_public(r) for r in request.app.state.db.walks(active, min(limit, 100))]


@app.get("/api/walks/{walk_id}")
async def get_walk(walk_id: str, request: Request):
    rec = request.app.state.db.walk(walk_id)
    if not rec or not walk_role(rec, request): raise HTTPException(404, "unknown walk")       # same answer for missing and not-yours
    return {**_public(rec), "live": request.app.state.runtime.status(walk_id)}


class ShareReq(BaseModel):
    active: bool


@app.post("/api/walks/{walk_id}/share")
async def share(walk_id: str, body: ShareReq, request: Request):
    """The walker turns live sharing off (revokes the guardian link, disconnects guardians, stops SMS and calls) or on (a new link)."""
    s = request.app.state; rec = s.db.walk(walk_id)
    if not rec or walk_role(rec, request) != "walker": raise HTTPException(404, "unknown walk")
    if rec["status"] == "ended": raise HTTPException(409, "This walk has ended; sharing already stopped.")
    token = secrets.token_urlsafe(18) if body.active else None
    s.db.update_walk(walk_id, sharing=body.active, guardian_token=token)
    url = guardian_url(request, walk_id, token)
    if not body.active: await s.hub.kick(walk_id, "guardian", 4401)
    await s.runtime.set_sharing(walk_id, body.active, url)
    await s.hub.publish(envelope(walk_id, {"type": "share.update", "active": body.active}, "engine"))
    log.info("walk %s sharing %s", walk_id, "on" if body.active else "off")
    return {"active": body.active, "guardianUrl": url}


def require_admin(request: Request):
    if settings.admin_token and not secrets.compare_digest(request.headers.get("x-admin-token", ""), settings.admin_token):
        raise HTTPException(401, "control room token required")


# ---------- shopkeepers ----------
def _night(open_until: str) -> tuple[int, int | None, float]:
    """(weekday the night started, open-until minute on that night's clock, expiry epoch at 6 AM next morning)."""
    now = datetime.now(SF); start = now - timedelta(days=1) if now.hour < 5 else now
    expires = (start + timedelta(days=1)).replace(hour=6, minute=0, second=0, microsecond=0).timestamp()
    if open_until == "closed": return start.weekday(), None, expires
    if open_until == "24h": return start.weekday(), 30 * 60, expires
    h, m = map(int, open_until.split(":")); return start.weekday(), h * 60 + m + (1440 if h < 12 else 0), expires


def _walks_near(app_state, ll, radius=80.0) -> list[str]:
    """Unfinished walks whose latest plan passes within `radius` m of a point (read from the rooms, so it works for either runtime)."""
    out = []
    for rec in app_state.db.walks(active_only=True, limit=100):
        room = app_state.hub.room(rec["id"], persistent=True)
        plan = next((e["msg"]["plan"] for e in reversed(room.history) if e["msg"].get("type") == "walk.plan"), None)
        data = plan and plan.get("data")
        if data and min(geo.project(data["route"], ll)[1], geo.project(data["shortest"], ll)[1]) <= radius: out.append(rec["id"])
    return out


@app.get("/api/places/{place_id}")
async def place_info(place_id: str, request: Request):
    s = request.app.state; info = s.port.place(place_id)
    if not info: raise HTTPException(404, "unknown place")
    decl = s.db.declaration(place_id)
    return dict(id=place_id, name=info["name"] or info["cat"].replace("_", " ").title(), cat=info["cat"], lngLat=info["ll"], listedHours=info["hours"],
                hoursSource=info.get("hours_source"), declaration=decl and dict(openUntil=decl["open_until"], safeHaven=bool(decl["safe_haven"]), frontLight=bool(decl["front_light"]),
                                                                              updatedAt=decl["updated_at"]), walksNearby=len(_walks_near(s, info["ll"])))


@app.post("/api/places/{place_id}/declaration")
async def declare(place_id: str, req: Declaration, request: Request):
    """A shopkeeper says 'open until 1 AM tonight'. Stored until 6 AM, applied to every plan, and pushed to walks passing the door."""
    limit(request, "shop"); s = request.app.state; info = s.port.place(place_id)
    if settings.production: require_admin(request)          # no shopkeeper accounts yet: on a public deploy only the crew can declare
    if not info: raise HTTPException(404, "unknown place")
    day, until, expires = _night(req.openUntil)
    s.db.set_declaration(place_id, day, until, req.openUntil, req.safeHaven, req.frontLight, expires); apply_declarations(request.app)
    near = _walks_near(s, info["ll"]); decl = req.model_dump()
    for wid in near: await s.hub.publish(envelope(wid, {"type": "place.update", "place": {"id": place_id, **decl}}, "shop"), observe=False)
    asyncio.create_task(s.runtime.place_update(place_id, decl, near))
    return dict(ok=True, walksNotified=len(near), expiresAt=expires)


# ---------- the Head (Claude) and the Checker ----------
class AskReq(BaseModel):
    text: str = Field(min_length=1, max_length=1000); session: str | None = Field(None, max_length=40)
    allowChecks: bool = False            # paid checks run only after the walker approves them (POST /api/head/approve)


def _store_plan(s, req: dict, data: dict, routes: dict) -> str:
    return s.plans.put(plan_key(req["origin"], req["destination"], req["day"], req["minute"]), data, routes)


def _with_plan(s, res: dict) -> dict:
    routes = res.pop("_routes", None); data = res.get("plan")
    if data and routes and res.get("req"):
        res["planId"] = _store_plan(s, res["req"], data, routes); res["plan"] = {"planId": res["planId"], **data}
    return res


@app.post("/api/head/ask")
async def head_ask(body: AskReq, request: Request):
    """Natural-language request → Professor Hoot (Claude) delegates to Scoot (routes) and Sherlock (evidence) → answer with a tool trace.
    A paid listing check is proposed as `pendingApproval` unless allowChecks is true."""
    limit(request, "head"); s = request.app.state
    # allowChecks lets Claude run a paid check without the approval card: only the control room may ask for that
    crew = bool(settings.admin_token) and secrets.compare_digest(request.headers.get("x-admin-token", ""), settings.admin_token)
    return _with_plan(s, await s.head.ask(body.text, body.session, body.allowChecks and crew))


class ApproveReq(BaseModel):
    session: str = Field(min_length=1, max_length=40); approvalId: str = Field(min_length=1, max_length=40); approve: bool


@app.post("/api/head/approve")
async def head_approve(body: ApproveReq, request: Request):
    """The walker answers Hoot's request to run a paid listing check: run exactly what was approved, re-score, explain."""
    limit(request, "head"); s = request.app.state
    try: res = await s.head.approve(body.session, body.approvalId, body.approve)
    except KeyError: raise HTTPException(404, "That approval expired or was already used. Ask again.") from None
    except PermissionError as e: raise HTTPException(429, str(e)) from None
    return _with_plan(s, res)


class CheckReq(BaseModel):
    planId: str = Field(max_length=40); placeIds: list[str] | None = Field(None, max_length=6)
    route: str = Field("best", pattern="^(best|fast|balanced)$"); confirm: bool = False


def _plan_by_id(s, pid: str):
    v = s.plans.items.get(pid)
    if not v or time.time() - v[0] > s.plans.ttl: raise HTTPException(404, "This plan expired. Plan the walk again.")
    return v


def _route_key(routes: dict, key: str) -> str: return key if key in routes else "best"


@app.post("/api/check/route")
async def check_route(body: CheckReq, request: Request):
    """Checker's inspection of the chosen route: "Good to go" or what to know (closures, empty stretches, lamp reports, lighting, transit)."""
    s = request.app.state; _, key, data, routes = _plan_by_id(s, body.planId)
    return await run_in_threadpool(inspect_route.inspect, s.engine, data, routes, _route_key(routes, body.route), key[4], key[5])


@app.post("/api/check/unknowns")
async def check_unknowns(body: CheckReq, request: Request):
    """Checker, no network: named places on the route whose hours are unknown (they earn no credit in the score)."""
    s = request.app.state; _, key, data, routes = _plan_by_id(s, body.planId); rk = _route_key(routes, body.route)
    places = await run_in_threadpool(hours_check.unknowns, s.engine, routes[rk]["coords"], key[4], key[5], 6)
    return {"places": places, "total": routes[rk].get("unknown_hours_nearby"), "apify": bool(settings.apify_token) or hours_check.mock_mode()}


@app.post("/api/check/hours")
async def check_hours(body: CheckReq, request: Request):
    """Checker, live: one Apify run over the listings of up to 6 unknown-hours places, then the Guide re-plans with the evidence.
    Requires confirm=true (the walker pressed the button). Places checked recently are reused, not re-billed."""
    if not body.confirm: raise HTTPException(428, "A listing check costs money. Send confirm: true once the walker has approved it.")
    limit(request, "check"); s = request.app.state; _, key, data, routes = _plan_by_id(s, body.planId); rk = _route_key(routes, body.route)
    places = await run_in_threadpool(hours_check.unknowns, s.engine, routes[rk]["coords"], key[4], key[5], 40 if body.placeIds else 6)
    if body.placeIds: places = [p for p in places if p["id"] in set(body.placeIds)]       # only unknown-hours places on this route, never arbitrary ids
    res = await hours_check.investigate(s.engine, places[:6], s.budget)
    o = {"lat": key[0], "lon": key[1], "name": data["start"]["name"]}; d = {"lat": key[2], "lon": key[3], "name": data["end"]["name"]}
    new, new_routes = (data, routes)
    if res["changed"]:
        avoid = [tuple(a) for a in routes.get("_avoid") or []] or None
        new, new_routes = await s.port.plan(o, d, key[4], key[5], "Walker", "Guardian", avoid=avoid)
        if avoid: new_routes = {**new_routes, "_avoid": routes["_avoid"]}
    pid = _store_plan(s, {"origin": o, "destination": d, "day": key[4], "minute": key[5]}, new, new_routes)
    return {**res, "before": data["stats"], "after": new["stats"], "routeChanged": new_routes["best"]["coords"] != routes["best"]["coords"], "planId": pid, "plan": {"planId": pid, **new}}


@app.get("/api/plans/{plan_id}/evidence")
async def plan_evidence(plan_id: str, request: Request, route: str = "best"):
    """Evidence Explorer: every named place along the route, its hours, whether it is listed open when you pass, and where that came from."""
    s = request.app.state; _, key, data, routes = _plan_by_id(s, plan_id); rk = _route_key(routes, route)
    return await run_in_threadpool(evidence_mod.route_evidence, s.engine, routes[rk]["coords"], key[4], key[5], rk)


# ---------- city layers ----------
@app.get("/api/why")
async def why(request: Request, lat: float, lon: float, day: int = 4, minute: int = 22 * 60 + 50):
    res = await run_in_threadpool(request.app.state.engine.why, "why", lat, lon, day, minute)
    if not res: raise HTTPException(404, "no street nearby")
    return res


@app.get("/api/area")
async def area(request: Request, lat: float, lon: float, day: int = 4, minute: int = 22 * 60 + 50, radius: float = 450.0):
    """Area dashboard: street-condition heat, listed state of every named place and the evening open curve around one point."""
    return await run_in_threadpool(request.app.state.engine.area, "area", lat, lon, day, minute, max(100.0, min(radius, 900.0)))


@app.get("/api/where")
async def where(request: Request, lat: float, lon: float):
    return await run_in_threadpool(request.app.state.engine.where, lat, lon)


@app.get("/api/debt")
async def debt(request: Request, day: int = 4, minute: int = 22 * 60 + 50): return await run_in_threadpool(request.app.state.engine.darkness_debt, day, minute)


@app.get("/api/audit/latest")
async def audit_latest(request: Request):
    return request.app.state.db.latest_audit() or {"ranking": [], "draft311": None, "ts": None}


# ------------------------------------------------------------------------------------------------ agents → rooms (uAgents runtime)
class Published(BaseModel):
    walkId: str = Field(max_length=64); msg: dict


@app.post("/api/internal/publish")
async def internal_publish(body: Published, request: Request):
    """The uAgents bureau publishes agent messages here. Only agent message types, only with the shared secret."""
    if settings.agent_runtime != "uagents" or not settings.bridge_secret or not secrets.compare_digest(request.headers.get("x-bridge-secret", ""), settings.bridge_secret):
        raise HTTPException(401, "bridge secret required")
    if body.msg.get("type") not in AGENT_TYPES: raise HTTPException(422, "not an agent message type")
    if body.msg["type"] == "audit.result" and not request.app.state.db.walk(body.walkId): return {"ok": True}
    await request.app.state.hub.publish(envelope(body.walkId, body.msg, "engine")); return {"ok": True}


# ------------------------------------------------------------------------------------------------ WebSocket rooms
@app.websocket("/ws")
async def ws_walk(sock: WebSocket, walk: str = "demo", role: str = "unknown", token: str = ""):
    s = sock.app.state; rec = s.db.walk(walk)
    if role not in ROLES or len(walk) > 64: await sock.close(code=1008); return
    if rec:
        if role == "walker" and not secrets.compare_digest(token, rec["walker_token"]): await sock.close(code=4401); return
        if role == "room" and settings.admin_token and not secrets.compare_digest(token, settings.admin_token): await sock.close(code=4401); return
        if role == "guardian" and not (rec.get("sharing") and rec.get("guardian_token") and secrets.compare_digest(token, rec["guardian_token"])):
            await sock.close(code=4401); return
        if role == "shop": await sock.close(code=1008); return
    elif not settings.demo_rooms:
        await sock.close(code=4404); return
    await sock.accept()
    await s.hub.join(walk, sock, role, persistent=rec is not None)
    if rec and role == "guardian":           # sharing may have been stopped while this socket was connecting
        now = s.db.walk(walk)
        if not (now and now.get("sharing") and now.get("guardian_token") and secrets.compare_digest(token, now["guardian_token"])):
            await s.hub.leave(walk, sock); await sock.close(code=4401); return
    try:
        while True:
            try: env = await sock.receive_json()
            except (ValueError, KeyError): continue
            if not isinstance(env, dict) or env.get("walkId") != walk or not isinstance(env.get("msg"), dict): continue
            if rec is None:                     # unregistered room: plain relay for the offline DemoEngine, no agents
                await s.hub.publish(env, exclude=sock, observe=False); continue
            msg = clean_client_msg(role, env["msg"])
            if msg is None or (role == "room" and msg["type"] == "walk.position" and not rec["replay"]): continue
            out = envelope(walk, msg, role)
            if isinstance(env.get("id"), str) and 0 < len(env["id"]) <= 64: out["id"] = env["id"]     # keep the sender's id so its own echo dedupes
            if msg["type"] == "walk.position":
                s.db.add_position(walk, time.time(), *msg["lngLat"], msg.get("speed"), msg.get("accuracy"), msg["replay"])
            await s.hub.publish(out, exclude=sock)
    except WebSocketDisconnect:
        pass
    finally:
        await s.hub.leave(walk, sock)


# ------------------------------------------------------------------------------------------------ the built PWA (single-process deploy)
WEB = ROOT / "web" / "dist"
if WEB.exists():
    app.mount("/assets", StaticFiles(directory=WEB / "assets"), name="assets")

    @app.get("/{path:path}")
    async def spa(path: str):
        if path.startswith(("api/", "ws")): raise HTTPException(404)
        f = (WEB / path).resolve()
        if f.is_file() and WEB.resolve() in f.parents: return FileResponse(f)
        if "." in path.rsplit("/", 1)[-1]: raise HTTPException(404)     # a missing file (e.g. tiles) must not come back as the app shell
        return FileResponse(WEB / "index.html")
