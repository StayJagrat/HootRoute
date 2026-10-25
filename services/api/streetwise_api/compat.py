"""Endpoints the ASI:One chat agents in services/agents (scout.py, rescuer.py, night_auditor.py) call over HTTP.

They plan inside named sessions and never touch the walk rooms the PWA uses.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api")
last_route: dict[str, dict] = {}


class LatLon(BaseModel): lat: float; lon: float
class RouteReq(BaseModel):
    session: str = "chat"; origin: LatLon; dest: LatLon
    day: int = Field(4, ge=0, le=6); minute: int = Field(22 * 60 + 50, ge=0, le=36 * 60)
class DeclareReq(BaseModel):
    session: str = "chat"; place_id: str; until_minute: int; day: int = 4; minute: int = 22 * 60 + 50
class SessionReq(BaseModel): session: str = "chat"


def _engine(request: Request): return request.app.state.engine


@router.get("/landmarks")
async def landmarks(request: Request): return _engine(request).landmarks()


@router.get("/places")
async def places(request: Request, session: str = "chat", day: int = 4, minute: int = 22 * 60 + 50):
    return await run_in_threadpool(_engine(request).places, session, day, minute)


@router.post("/route")
async def route(req: RouteReq, request: Request):
    out = await run_in_threadpool(_engine(request).route, req.session, (req.origin.lat, req.origin.lon), (req.dest.lat, req.dest.lon), req.day, req.minute)
    last_route[req.session] = dict(req=req.model_dump(), out=out); return out


@router.post("/agents/place/suggest")
async def suggest(req: SessionReq, request: Request):
    lr = last_route.get(req.session)
    if not lr: raise HTTPException(409, "plan a route first")
    fast = next(r for r in lr["out"]["routes"] if r["id"] == "fast"); q = lr["req"]
    return await run_in_threadpool(_engine(request).suggest_declarations, req.session, fast, q["day"], q["minute"])


@router.post("/agents/place/declare")
async def declare(req: DeclareReq, request: Request):
    engine = _engine(request)
    try: info = await run_in_threadpool(engine.declare, req.session, req.place_id, req.until_minute, req.day, req.minute)
    except KeyError: raise HTTPException(404, "unknown place")
    lr = last_route.get(req.session)
    if not lr: return dict(declared=info, route=None)
    q = lr["req"]; out = await run_in_threadpool(engine.route, req.session, (q["origin"]["lat"], q["origin"]["lon"]), (q["dest"]["lat"], q["dest"]["lon"]), q["day"], q["minute"])
    before = {r["id"]: r["score"] for r in lr["out"]["routes"]}; last_route[req.session] = dict(req=q, out=out)
    return dict(declared=info, route=out, before=before)


@router.post("/agents/auditor/run")
async def audit(req: SessionReq, request: Request):
    lr = last_route.get(req.session)
    rec = next((r for r in lr["out"]["routes"] if r["id"] == lr["out"]["recommended"]), None) if lr else None
    return await run_in_threadpool(_engine(request).audit, rec)


@router.post("/session/reset")
async def reset(req: SessionReq, request: Request):
    _engine(request).clear(req.session); last_route.pop(req.session, None); return dict(ok=True)
