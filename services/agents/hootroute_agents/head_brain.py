"""Professor Hoot (the Head): Claude reads the walker's request, delegates to Scoot McRoute (routing) and Sherlock Hoots
(evidence), and explains the result. Claude chooses tools and words; it never produces a number. Every score, time and
distance in the answer must appear in a tool result: `numbers_check` verifies that, and an answer that fails is replaced
by a deterministic summary. The trace records each call (agent, tool, the reason Claude gave, timing) for the UI.

Paid listing checks never run on Claude's say-so: Claude can only *propose* one (propose_hours_check); the walker approves
it (POST /api/head/approve) and then exactly the approved places are checked.

Limits: at most MAX_TOOL_CALLS tool calls and DEADLINE_S seconds per request; independent read-only calls in one turn run
concurrently; malformed tool arguments are rejected before they reach the engine; with no ANTHROPIC_API_KEY a fixed
pipeline runs instead and says so.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

from . import hours_check, inspect_route
from .brand import BRAND, PERSONA
from .preferences import Preferences, choose_option
from .config import env

log = logging.getLogger("hootroute.head")
SF = ZoneInfo("America/Los_Angeles")
API = "https://api.anthropic.com/v1/messages"
MAX_TOOL_CALLS = 8
DEADLINE_S = 150
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
BANNED = re.compile(r"\b(safe(st|r)?|unsafe|dangerous|sketchy)\b", re.I)


def model() -> str: return env("HEAD_MODEL", "claude-sonnet-5-5")
def report_model() -> str: return env("HEAD_REPORT_MODEL", "claude-haiku-5-5")
def enabled() -> bool: return bool(env("ANTHROPIC_API_KEY"))


async def claude(messages: list, system: str, tools: list | None = None, max_tokens: int = 900, mdl: str | None = None, timeout: float = 45) -> dict:
    body = {"model": mdl or model(), "max_tokens": max_tokens, "system": system, "messages": messages}
    if tools: body["tools"] = tools
    async with httpx.AsyncClient(timeout=timeout) as c:
        r = await c.post(API, json=body, headers={"x-api-key": env("ANTHROPIC_API_KEY"), "anthropic-version": "2023-06-01", "content-type": "application/json"})
    if r.status_code != 200: raise RuntimeError(f"Claude API {r.status_code}: {r.text[:200]}")
    return r.json()


def clean(text: str) -> str:
    """House rule: conditions, not a safety rating. Replace the words we never use rather than ship them."""
    return BANNED.sub(lambda m: {"safe": "comfortable", "safest": "best-lit", "safer": "better-lit"}.get(m.group(0).lower(), "lower-scoring"), text)


# ------------------------------------------------------------------------------------------------ the walk report
REPORT_SYSTEM = f"""You write the end-of-walk report for {BRAND}, a walking companion for late-shift workers in San Francisco.
Write 3 to 4 short plain sentences for the walker and the person watching over them. Use ONLY the JSON facts given; never add numbers,
places or events that are not in the facts. Say what happened (route, time, check-ins, any alert and who answered), then one useful
note about the route's conditions or the open 311 streetlight cases (say they are drafts, nothing was submitted). If replay is true, say
it was a replayed demo walk. Never use the words safe, unsafe, dangerous or sketchy: these are route conditions, not a safety rating."""


def template_report(f: dict) -> str:
    s = (f"{f['walker']} walked {f['from']} → {f['to']} on the {f['route']} route in about {f['minutes']} min (route score {f['score']}, "
         f"longest stretch with nothing listed open {f['longest_empty_m']} m). ")
    s += f"{f['checkins']} check-in{'s' if f['checkins'] != 1 else ''}"
    s += (f"; one alert ({f['alert_reason']}), cleared by {f['acked_by']}." if f["alerts"] and f["acked_by"] else f"; one alert ({f['alert_reason']})." if f["alerts"] else "; no alerts.")
    cases = f["open_311_streetlight_cases"]
    s += f" {len(cases)} open SF 311 streetlight case{'s' if len(cases) != 1 else ''} on the route; a draft follow-up is ready, nothing was submitted." if cases else " No open SF 311 streetlight case on the route."
    return s + (" (Replayed demo walk.)" if f.get("replay") else "")


async def write_report(facts: dict) -> tuple[str, str]:
    """(report text, who wrote it). Claude writes it from the facts; the template is the fallback."""
    if not enabled(): return template_report(facts), "template (Claude not configured)"
    try:
        r = await claude([{"role": "user", "content": json.dumps(facts)}], REPORT_SYSTEM, max_tokens=300, mdl=report_model(), timeout=15)
        text = "".join(b.get("text", "") for b in r.get("content", []) if b.get("type") == "text").strip()
        if text: return clean(text), f"Claude ({report_model()})"
    except Exception as e:
        log.warning("report fallback: %s", e)
    return template_report(facts), "template (Claude unavailable)"


# ------------------------------------------------------------------------------------------------ recovery explanation
RECOVERY_SYSTEM = f"""You are Professor Hoot, the coordinator in {BRAND}. A walker reported a problem during their walk and the routing engine
returned alternatives from where they are. In 2 to 3 short plain sentences, say which option avoids the report and what it costs in minutes,
using ONLY the numbers in the JSON. Say the current route stays active until they choose. Never use the words safe, unsafe, dangerous or sketchy."""


def template_recovery(f: dict) -> str:
    opts = [o for o in f["options"] if o["avoidsReport"]] or f["options"]
    if not opts: return f"I couldn't find another way from {f['from']}. Your current route stays active."
    best = min(opts, key=lambda o: o["stats"]["minutes"])
    return (f"{best['label']} avoids the {f['report']} report: {best['stats']['minutes']} min from {f['from']} (your current route has about "
            f"{f['current_remaining']['minutes']} min left). Its longest stretch with nothing listed open is {best['stats']['longestEmptyM']} m. "
            "Your current route stays active until you choose. Conditions, not a safety rating.")


async def explain_recovery(facts: dict) -> tuple[str, str]:
    if enabled():
        try:
            r = await claude([{"role": "user", "content": json.dumps(facts)}], RECOVERY_SYSTEM, max_tokens=220, mdl=report_model(), timeout=12)
            text = clean("".join(b.get("text", "") for b in r.get("content", []) if b.get("type") == "text").strip())
            chk = numbers_check(text, [facts])
            if text and chk["ok"]: return text, f"Claude ({report_model()})"
            if text: log.warning("recovery explanation had unverified numbers %s; using the template", chk["unverified"])
        except Exception as e:
            log.warning("recovery explanation fallback: %s", e)
    return template_recovery(facts), "template"


# ------------------------------------------------------------------------------------------------ numbers check
NUM = re.compile(r"(?<![\w.])\d+(?:[.,]\d+)?(?![\w])")
GEO_KEYS = {"lat", "lon", "lng", "lngLat", "ll", "coords", "route", "shortest", "line", "stopAt", "id", "place_ids", "candidates_ll", "customGeolocation", "polygon"}
CLOCK = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*([AaPp])\.?[Mm]\.?")


def _norm(x: float) -> set[str]:
    out = {f"{x:g}", f"{round(x)}", f"{round(x, 1):g}"}
    if abs(x) >= 1000: out |= {f"{x / 1000:g}", f"{round(x / 1000, 1):g}", f"{round(x / 1000, 2):g}"}       # metres as km
    return out


def _numbers_in(obj, out: set, minutes: set, pairs: list):
    if isinstance(obj, bool): return
    if isinstance(obj, (int, float)):
        out |= _norm(float(obj))
        if isinstance(obj, int) and 0 <= obj < 3000: minutes.add(obj % 1440)
        return
    if isinstance(obj, str):
        for m in NUM.findall(obj): out |= _norm(float(m.replace(",", "")))
        for h, mm, ap in CLOCK.findall(obj): minutes.add(((int(h) % 12) + (12 if ap.lower() == "p" else 0)) * 60 + int(mm or 0))
        return
    if isinstance(obj, dict):
        for a, b in (("recommended", "fastest"), ("before", "after"), ("hootroute", "shortest")):
            if isinstance(obj.get(a), dict) and isinstance(obj.get(b), dict): pairs.append((obj[a], obj[b]))
        for k, v in obj.items():
            if k not in GEO_KEYS: _numbers_in(v, out, minutes, pairs)
    elif isinstance(obj, (list, tuple)):
        for v in obj: _numbers_in(v, out, minutes, pairs)


def numbers_check(answer: str, sources: list) -> dict:
    """Every number in `answer` must appear in a tool result (or be a difference of two of the same stat, a clock time of a
    minute in a result, or a small count). Returns {ok, unverified}."""
    allowed: set[str] = set(); minutes: set[int] = set(); pairs: list = []
    for src in sources: _numbers_in(src, allowed, minutes, pairs)
    for a, b in pairs:
        for k in set(a) & set(b):
            if isinstance(a[k], (int, float)) and isinstance(b[k], (int, float)) and not isinstance(a[k], bool): allowed |= _norm(abs(a[k] - b[k]))
    bad = []
    text = answer
    for m in CLOCK.finditer(answer):
        h, mm, ap = m.group(1), m.group(2), m.group(3)
        mins = ((int(h) % 12) + (12 if ap.lower() == "p" else 0)) * 60 + int(mm or 0)
        if not any(abs(mins - x) <= 1 or abs(mins - x) >= 1439 for x in minutes): bad.append(m.group(0))
        text = text.replace(m.group(0), " ")
    for tok in NUM.findall(text):
        v = float(tok.replace(",", ""))
        if v <= 12 and v == int(v): continue                                    # counts and ordinals ("2 places", "step 3")
        if tok.replace(",", "") not in allowed and not (_norm(v) & allowed): bad.append(tok)
    return {"ok": not bad, "unverified": bad[:8]}


# ------------------------------------------------------------------------------------------------ tools
POINT = {"type": "object", "properties": {"name": {"type": "string"}, "lat": {"type": "number"}, "lon": {"type": "number"}}, "required": ["name", "lat", "lon"]}
WHY = {"why": {"type": "string", "description": "One short sentence: why you are calling this tool now. Shown to the walker in the agent trace."}}
ROUTE_ENUM = {"type": "string", "enum": ["recommended", "fastest", "balanced"]}


def _tool(name, desc, props, required):
    return {"name": name, "description": desc, "input_schema": {"type": "object", "properties": {**props, **WHY}, "required": required}}


TOOLS = [
    _tool("find_place", "Scoot McRoute: look up a place, landmark or street in San Francisco. Returns candidates with coordinates. Use before plan_routes for any named place.",
          {"query": {"type": "string"}}, ["query"]),
    _tool("plan_routes", "Scoot McRoute: plan and score the fastest walking route, a balanced one and the HootRoute route between two points at a departure time. "
          "Scores (0-100) come from a deterministic engine: listed-open places, gaps between them, help points, mapped lighting, main roads, transit running, turns. No crime data.",
          {"origin": POINT, "destination": POINT, "day": {"type": "integer", "minimum": 0, "maximum": 6, "description": "0 = Monday"},
           "minute": {"type": "integer", "minimum": 0, "maximum": 1439, "description": "minutes after midnight, San Francisco time"}},
          ["origin", "destination", "day", "minute"]),
    _tool("rank_by_preferences", "Scoot McRoute: choose among the planned candidate routes by the walker's stated preferences (deterministic rule; the scores do not change).",
          {"fewerTurns": {"type": "boolean"}, "preferOpenPlaces": {"type": "boolean"}, "preferMainRoads": {"type": "boolean"}, "fastest": {"type": "boolean"},
           "lowDistraction": {"type": "boolean", "description": "simpler, quieter guidance; does not pick a route"}}, []),
    _tool("inspect_route", "Sherlock Hoots: walk the planned route on the map and report what to know: permitted street closures and construction, the longest stretch with nothing listed open, open streetlight reports, mapped lighting, unknown hours, and whether BART runs at arrival. Returns a verdict (Good to go / Heads up).",
          {"route": ROUTE_ENUM}, ["route"]),
    _tool("find_route_unknowns", "Sherlock Hoots: list named places right on the planned route whose opening hours are unknown. Unknown hours earn no credit in the score, so they can hide open places.",
          {"route": ROUTE_ENUM, "limit": {"type": "integer", "minimum": 1, "maximum": 6}}, ["route"]),
    _tool("propose_hours_check", "Sherlock Hoots: ask the walker to approve a live check of the published listings of up to 4 places returned by find_route_unknowns. "
          "This does NOT run the check; it costs money, so the walker decides. Use it only when the answer could change their decision.",
          {"place_ids": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 4}, "reason": {"type": "string"}}, ["place_ids", "reason"]),
    _tool("check_listed_hours", "Sherlock Hoots: run the live Apify Google Maps check on places returned by find_route_unknowns (30-90 s, a few cents). "
          "Only available when the walker already approved checks. Found hours become evidence for the engine. A listing is not proof a place is staffed.",
          {"place_ids": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 6}}, ["place_ids"]),
    _tool("rescore_routes", "Scoot McRoute: plan the same walk again with any new hours evidence and report before/after scores and whether the recommended route changed.", {}, []),
    _tool("replan_avoiding", "Scoot McRoute: the walker says something is blocked, closed or under construction at a point. Plan the same walk again avoiding the streets within radius_m of it, "
          "and report the new options next to the old ones.", {"near": POINT, "radius_m": {"type": "integer", "minimum": 15, "maximum": 150}}, ["near"]),
]
AGENT_OF = {"inspect_route": "checker", "find_place": "guide", "plan_routes": "guide", "find_route_unknowns": "checker", "propose_hours_check": "checker",
            "check_listed_hours": "checker", "rescore_routes": "guide", "replan_avoiding": "guide", "rank_by_preferences": "guide"}
READ_ONLY = {"find_place", "inspect_route", "find_route_unknowns"}           # safe to run concurrently in one turn
APPROVAL_TTL_S = 600
MAX_USD = 0.5


def system_prompt(now: datetime, session: dict | None, allow_checks: bool) -> str:
    cur = (f"\nThe walker already has a plan in this conversation: {session['origin']['name']} → {session['destination']['name']}, "
           f"{DAYS[session['day']]} at {session['minute'] // 60 % 24:02d}:{session['minute'] % 60:02d}. Work on it unless they ask for a different walk.") if session else ""
    return f"""You are Professor Hoot, the coordinator of {BRAND}, a journey companion for people walking in San Francisco after dark: students leaving late
classes or libraries, and late-shift hospitality, healthcare, retail and cleaning workers. You coordinate two specialists through tools:
Scoot McRoute (find_place, plan_routes, rank_by_preferences, rescore_routes, replan_avoiding) and Sherlock Hoots (inspect_route, find_route_unknowns,
propose_hours_check{', check_listed_hours' if allow_checks else ''}).
It is now {DAYS[now.weekday()]} {now.strftime('%-I:%M %p')} in San Francisco (day {now.weekday()}, minute {now.hour * 60 + now.minute}). If no time is given, plan for now.
{cur}
How to work (give every call a short `why`):
1. Resolve places with find_place (several in one turn is fine), then plan_routes.
2. If the walker states preferences (fewer turns or simpler directions, main roads, fastest, places listed open on the way, low-distraction guidance), call rank_by_preferences.
3. Have Sherlock inspect_route the recommended route, then find_route_unknowns.
4. {"If unknown hours could change the decision, call check_listed_hours on up to 4 of them, then rescore_routes." if allow_checks else
    "If unknown hours could change the decision (the walker wants places open on the way, or the route has a long empty stretch), call propose_hours_check with up to 4 place ids and a one-sentence reason. It does not run anything: the walker approves it. Do not claim any check ran."}
5. If the walker reports something blocked, closed or under construction, find_place it and call replan_avoiding.
6. Answer in at most 5 short sentences of plain text (no headings, no lists), clock times like 11:30 PM. Start with Sherlock's verdict ("Good to go" or "Heads up"):
   which route and why, the numbers from the tools (score, minutes, longest stretch with nothing listed open), what is unknown, and what you propose to check or what changed. If nothing changed, say so.

Rules: every number you state must appear in a tool result. Unknown hours are unknown, not closed and not a risk. Published hours are not proof a place is staffed.
Do not claim real-time arrivals, live crowd levels or that anyone was contacted. Say "conditions, not a safety rating" once. Never use the words safe, unsafe,
dangerous or sketchy. {BRAND} never calls 911. If a place is outside San Francisco or cannot be found, say so and ask for another place."""


class Session:
    """One walker's planning conversation (PWA tab or ASI:One chat)."""
    def __init__(self):
        self.plan: dict | None = None; self.routes: dict | None = None; self.req: dict | None = None; self.unknowns: list = []; self.ts = time.time()
        self.history: list[dict] = []      # text-only turns, so a follow-up ("check those hours") keeps its context
        self.approvals: dict[str, dict] = {}
        self.preferences: Preferences | None = None


def event(name: str, args: dict, res: dict, ms: int, why: str, t0: float, group: int | None = None) -> dict:
    agent = AGENT_OF.get(name, "head"); status = "needs_approval" if res.get("status") == "needs_approval" else "error" if "error" in res else "ok"
    ok = status != "error" and res.get("ok", True) is not False
    return {"id": uuid.uuid4().hex[:10], "agent": agent, "persona": PERSONA.get(agent, agent), "tool": name, "why": (why or "")[:200],
            "input": {k: v for k, v in args.items() if k != "why"}, "ok": ok, "status": status if ok or status == "error" else "error",
            "startedAt": round(t0 * 1000), "ms": ms, "summary": brief(name, res), **({"group": group} if group is not None else {})}


class HeadBrain:
    def __init__(self, port, engine, budget=None):
        self.port, self.engine, self.budget = port, engine, budget; self.sessions: dict[str, Session] = {}

    def session(self, sid: str | None) -> tuple[str, Session]:
        now = time.time(); self.sessions = {k: v for k, v in self.sessions.items() if now - v.ts < 3600}
        sid = sid or uuid.uuid4().hex[:12]; s = self.sessions.setdefault(sid, Session()); s.ts = now; return sid, s

    # ---------- tool implementations ----------
    async def _plan(self, s: Session, req: dict, out: dict) -> dict:
        o, d = req["origin"], req["destination"]
        try: data, routes = await self.port.plan(o, d, req["day"], req["minute"], "Walker", "Guardian", avoid=req.get("avoid"))
        except ValueError as e: return {"error": str(e)}
        if req.get("avoid"): routes = {**routes, "_avoid": [list(a) for a in req["avoid"]]}      # later re-plans of this plan keep avoiding it
        s.plan, s.routes, s.req = data, routes, req; s.unknowns = []
        out["plan"] = data; out["routes"] = routes; out["req"] = {k: v for k, v in req.items() if k != "avoid"}
        if s.preferences: out["preferenceChoice"] = choose_option(data.get("options") or [], s.preferences)
        return summarize(data, routes)

    async def tool(self, s: Session, name: str, args: dict, out: dict, allow_checks: bool = False) -> dict:
        if name == "find_place":
            q = str(args.get("query", ""))[:80]
            hits = await asyncio.to_thread(self.engine.search, q, 5)
            return {"candidates": hits} if hits else {"candidates": [], "note": "No match in the San Francisco map. Try a landmark, a street or a business name."}
        if name == "plan_routes":
            o, d = args["origin"], args["destination"]
            for p in (o, d):
                if not (37.6 <= float(p["lat"]) <= 37.9 and -122.6 <= float(p["lon"]) <= -122.3): return {"error": f"{p['name']} is outside San Francisco"}
            res = await self._plan(s, {"origin": o, "destination": d, "day": int(args["day"]) % 7, "minute": int(args["minute"]) % 1440}, out)
            if "error" not in res: out.setdefault("before", s.plan["stats"])
            return res
        if name == "rank_by_preferences":
            s.preferences = Preferences(**{k: bool(args.get(k)) for k in ("fewerTurns", "preferOpenPlaces", "preferMainRoads", "fastest", "lowDistraction")})
            out["preferences"] = s.preferences.model_dump()
            if not s.plan: return {"ok": True, "preferences": out["preferences"], "note": "Saved. They apply once a walk is planned."}
            ch = choose_option(s.plan.get("options") or [], s.preferences); out["preferenceChoice"] = ch
            return {"ok": True, "choice": ch, "options": [{"id": o["id"], "label": o["label"], **o["stats"], "turnsPerKm": o.get("turnsPerKm"), "mainPct": o.get("mainPct"),
                                                           "placesOpen": o.get("placesOpen")} for o in s.plan.get("options") or []]}
        if not s.plan: return {"error": "No walk planned yet. Call plan_routes first."}
        key = {"fastest": "fast", "balanced": "balanced"}.get(args.get("route"), "best"); key = key if key in s.routes else "best"
        if name == "inspect_route":
            ins = await asyncio.to_thread(inspect_route.inspect, self.engine, s.plan, s.routes, key, s.req["day"], s.req["minute"])
            out["inspection"] = ins
            return {"verdict": ins["verdict"], "items": [{k: i[k] for k in ("level", "title", "detail")} for i in ins["items"]], "missing": ins["missing"]}
        if name == "find_route_unknowns":
            limit = max(1, min(6, int(args.get("limit", 5))))
            s.unknowns = await asyncio.to_thread(hours_check.unknowns, self.engine, s.routes[key]["coords"], s.req["day"], s.req["minute"], limit)
            out["unknowns"] = s.unknowns
            return {"places": [{k: p[k] for k in ("id", "name", "cat", "atM", "passMinute")} for p in s.unknowns], "count": len(s.unknowns),
                    "route_unknown_total": s.routes[key].get("unknown_hours_nearby")}
        if name == "propose_hours_check":
            known = {p["id"]: p for p in s.unknowns}; places = [known[str(i)] for i in args.get("place_ids", [])[:4] if str(i) in known]
            if not places: return {"error": "Only places returned by find_route_unknowns can be proposed."}
            provider = "mock" if hours_check.mock_mode() else "apify" if env("APIFY_TOKEN") else "unavailable"
            ap = {"id": uuid.uuid4().hex[:12], "action": "check_listed_hours", "provider": provider, "maxUsd": MAX_USD, "reason": str(args.get("reason") or "")[:240],
                  "places": [{k: p[k] for k in ("id", "name", "cat", "passMinute", "atM")} for p in places], "expiresAt": round((time.time() + APPROVAL_TTL_S) * 1000),
                  "_places": places}
            s.approvals = {k: v for k, v in s.approvals.items() if v["expiresAt"] > time.time() * 1000}; s.approvals[ap["id"]] = ap
            out["pendingApproval"] = {k: v for k, v in ap.items() if not k.startswith("_")}
            return {"status": "needs_approval", "approval_id": ap["id"], "provider": provider, "places": len(places),
                    "note": "Waiting for the walker to approve. Nothing has been checked." if provider != "unavailable" else "Live checks are not configured on this server; tell the walker hours stay unknown."}
        if name == "check_listed_hours":
            if not allow_checks: return {"error": "The walker has not approved a paid check. Use propose_hours_check."}
            known = {p["id"]: p for p in s.unknowns}; places = [known[str(i)] for i in args.get("place_ids", [])[:6] if str(i) in known]
            if not places: return {"error": "Only places returned by find_route_unknowns can be checked."}
            return await self._check(s, places, out)
        if name == "rescore_routes":
            before = s.plan["stats"]; old_best = s.routes["best"]["coords"]
            res = await self._plan(s, s.req, out)
            if "error" in res: return res
            out["after"] = s.plan["stats"]; out["routeChanged"] = s.routes["best"]["coords"] != old_best
            return {"before": before, "after": s.plan["stats"], "recommended_route_changed": out["routeChanged"]}
        if name == "replan_avoiding":
            n = args["near"]; r = max(15, min(150, int(args.get("radius_m", 40))))
            if not (37.6 <= float(n["lat"]) <= 37.9 and -122.6 <= float(n["lon"]) <= -122.3): return {"error": f"{n.get('name', 'That point')} is outside San Francisco"}
            before = summarize(s.plan, s.routes); old_best = s.routes["best"]["coords"]
            req = {**s.req, "avoid": [*(s.req.get("avoid") or []), (float(n["lat"]), float(n["lon"]), r)]}
            res = await self._plan(s, req, out)
            if "error" in res: return res
            out["after"] = s.plan["stats"]; out["routeChanged"] = s.routes["best"]["coords"] != old_best
            return {"avoiding": {"name": n.get("name"), "radius_m": r}, "before": before, "after": res,
                    "options_avoid_report": {o["id"]: o.get("avoidsReport", True) for o in s.plan.get("options") or []}}
        return {"error": f"unknown tool {name}"}

    async def _check(self, s: Session, places: list[dict], out: dict) -> dict:
        res = await hours_check.investigate(self.engine, places, self.budget)
        out["check"] = {k: v for k, v in res.items() if k != "evidence"}; out["evidence"] = res["evidence"]
        return {"ok": res["ok"], "note": res["note"], "evidence_applied": res["changed"], "reused": res["reused"], "seconds": (res.get("run") or {}).get("seconds"),
                "run_id": (res.get("run") or {}).get("runId"), "results": [{k: r.get(k) for k in ("name", "status", "hours", "source", "checkedAt")} for r in res["results"]]}

    # ---------- entry points ----------
    async def ask(self, text: str, sid: str | None = None, allow_checks: bool = False, history: list[dict] | None = None) -> dict:
        sid, s = self.session(sid); t0 = time.time(); trace: list[dict] = []; out: dict = {}; sources: list = [text]
        prior = s.req
        if not enabled():
            ans = await self.fallback(text, s, allow_checks, trace, out)
            return self.result(sid, s, ans, "fixed pipeline (Claude not configured)", trace, out, t0, {"ok": True, "unverified": []})
        now = datetime.now(SF)
        msgs = (list(history) if history else list(s.history))[-8:] + [{"role": "user", "content": text[:1000]}]
        sysmsg = system_prompt(now, prior, allow_checks)
        tools = [t for t in TOOLS if allow_checks or t["name"] != "check_listed_hours"]
        answer = ""; calls = 0; group = 0
        try:
            while True:
                r = await claude(msgs, sysmsg, tools)
                blocks = r.get("content", []); msgs.append({"role": "assistant", "content": blocks})
                uses = [b for b in blocks if b.get("type") == "tool_use"]
                if not uses or r.get("stop_reason") != "tool_use":
                    answer = "".join(b.get("text", "") for b in blocks if b.get("type") == "text").strip(); break
                lead = " ".join(b.get("text", "") for b in blocks if b.get("type") == "text").strip()

                async def run_one(u, grp):
                    nonlocal calls
                    calls += 1; ts = time.time(); args = u.get("input") or {}
                    if calls > MAX_TOOL_CALLS or time.time() - t0 > DEADLINE_S: res = {"error": "Tool budget reached. Answer with what you have."}
                    else:
                        try: res = await asyncio.wait_for(self.tool(s, u["name"], args, out, allow_checks), timeout=max(5.0, DEADLINE_S - (time.time() - t0)))
                        except (KeyError, TypeError, ValueError) as e: res = {"error": f"Invalid arguments: {e}"}
                        except asyncio.TimeoutError: res = {"error": "This step ran out of time."}
                    sources.append(res)
                    ev = event(u["name"], args, res, round((time.time() - ts) * 1000), str(args.get("why") or lead), ts, grp)
                    return {"type": "tool_result", "tool_use_id": u["id"], "content": json.dumps(res, default=str)[:6000]}, ev

                if len(uses) > 1 and all(u["name"] in READ_ONLY for u in uses):
                    group += 1; done = list(await asyncio.gather(*(run_one(u, group) for u in uses)))
                else:
                    done = [await run_one(u, None) for u in uses]
                results = [r for r, _ in done]; trace.extend(ev for _, ev in done)       # trace keeps Claude's call order
                msgs.append({"role": "user", "content": results})
                if calls > MAX_TOOL_CALLS + 2: break
        except Exception as e:
            log.warning("Claude orchestration failed: %s", e)
            if not out.get("plan"):
                ans = await self.fallback(text, s, allow_checks, trace, out)
                return self.result(sid, s, ans, f"fixed pipeline (Claude error: {type(e).__name__})", trace, out, t0, {"ok": True, "unverified": []})
            answer = answer or ""
        answer = clean(answer); by = f"Claude ({model()})"
        chk = numbers_check(answer, sources)
        if not answer or not chk["ok"]:
            if answer: log.warning("Hoot's answer had numbers not found in tool results: %s", chk["unverified"])
            answer = self.facts_text(s, out) if s.plan else (answer or "I couldn't finish that. Try again with a start and a destination.")
            by += " · prose replaced by engine summary" + (" (unverified numbers)" if not chk["ok"] else "")
        s.history += [{"role": "user", "content": text[:1000]}, {"role": "assistant", "content": answer or "(no answer)"}]
        return self.result(sid, s, answer, by, trace, out, t0, chk)

    async def approve(self, sid: str, approval_id: str, approve: bool) -> dict:
        """The walker's answer to a proposed check. Runs exactly the approved places, re-scores, explains."""
        if sid not in self.sessions: raise KeyError(sid)
        _, s = self.session(sid); ap = s.approvals.pop(approval_id, None)
        if not ap or ap["expiresAt"] < time.time() * 1000: raise KeyError(approval_id)
        t0 = time.time(); trace: list[dict] = []; out: dict = {}
        if not approve:
            trace.append(event("check_listed_hours", {"place_ids": [p["id"] for p in ap["places"]]}, {"status": "skipped", "ok": True, "note": "declined"}, 0, "The walker declined the check.", t0))
            trace[-1]["status"] = "skipped"
            return self.result(sid, s, "Okay, I didn't check anything. Those places stay unknown, and the route numbers are unchanged. Conditions, not a safety rating.",
                               "Professor Hoot", trace, out, t0, {"ok": True, "unverified": []})
        if ap["provider"] == "unavailable":
            return self.result(sid, s, "Live listing checks are not configured on this server, so nothing was checked. Those hours stay unknown.", "Professor Hoot", trace, out, t0,
                               {"ok": True, "unverified": []})
        if not s.plan: raise KeyError(approval_id)
        before = s.plan["stats"]; out["before"] = before
        ts = time.time(); res = await self._check(s, ap["_places"], out)
        trace.append(event("check_listed_hours", {"place_ids": [p["id"] for p in ap["places"]]}, res, round((time.time() - ts) * 1000), "The walker approved: " + ap["reason"], ts))
        ts = time.time(); old_best = s.routes["best"]["coords"]
        if res.get("evidence_applied"):
            rs = await self._plan(s, s.req, out)
            out["routeChanged"] = s.routes["best"]["coords"] != old_best
            rres = {"before": before, "after": s.plan["stats"], "recommended_route_changed": out["routeChanged"]} if "error" not in rs else rs
            trace.append(event("rescore_routes", {}, rres, round((time.time() - ts) * 1000), "New hours evidence: score the same walk again.", ts))
        else:
            out["routeChanged"] = False; out["plan"] = s.plan; out["routes"] = s.routes; out["req"] = {k: v for k, v in s.req.items() if k != "avoid"}
        out["after"] = s.plan["stats"]
        facts = {"check": res, "before": before, "after": s.plan["stats"], "route_changed": out["routeChanged"]}
        answer, by = await self.explain_change(facts)
        return self.result(sid, s, answer, by, trace, out, t0, numbers_check(answer, [facts]))

    async def explain_change(self, facts: dict) -> tuple[str, str]:
        b, a = facts["before"]["hootroute"], facts["after"]["hootroute"]; chk = facts["check"]
        found = sum(1 for r in chk["results"] if r["status"] == "hours found")
        tmpl = (f"Sherlock checked {len(chk['results'])} listing{'s' if len(chk['results']) != 1 else ''}: {found} published hours"
                + (f", {chk['reused']} reused from an earlier check" if chk.get("reused") else "") + ". "
                + (f"Scoot re-scored the walk: {b['score']} → {a['score']}, longest stretch with nothing listed open {b['longestEmptyM']} m → {a['longestEmptyM']} m. " if chk["evidence_applied"]
                   else "Nothing new to apply, so the scores are unchanged. ")
                + ("The recommended route changed. " if facts["route_changed"] else "The recommended route is the same. ")
                + ("" if chk["ok"] else chk["note"] + " ") + "Published hours are not proof a place is staffed. Conditions, not a safety rating.")
        if not enabled(): return tmpl, "template (Claude not configured)"
        try:
            r = await claude([{"role": "user", "content": json.dumps(facts, default=str)}],
                             f"You are Professor Hoot in {BRAND}. Explain in 2 to 3 short plain sentences what the listing check found and what changed in the route numbers, "
                             "or why nothing changed. Use ONLY numbers in the JSON. Published hours are not proof a place is staffed. Never use safe, unsafe, dangerous or sketchy.",
                             max_tokens=250, mdl=report_model(), timeout=15)
            text = clean("".join(x.get("text", "") for x in r.get("content", []) if x.get("type") == "text").strip())
            if text and numbers_check(text, [facts])["ok"]: return text, f"Claude ({report_model()})"
        except Exception as e:
            log.warning("explain_change fallback: %s", e)
        return tmpl, "template"

    def facts_text(self, s: Session, out: dict) -> str:
        st = s.plan["stats"]; ins = out.get("inspection") or {}
        msg = (f"{ins.get('verdict', 'Planned')}. HootRoute route: score {st['hootroute']['score']} vs {st['shortest']['score']} for the fastest, "
               f"{st['hootroute']['minutes']} vs {st['shortest']['minutes']} min, longest stretch with nothing listed open {st['hootroute']['longestEmptyM']} m vs {st['shortest']['longestEmptyM']} m. ")
        if out.get("preferenceChoice"): msg += out["preferenceChoice"]["reason"] + " "
        if out.get("after") and out.get("before"):
            msg += f"After the update the score is {out['after']['hootroute']['score']} (was {out['before']['hootroute']['score']}). "
        if out.get("pendingApproval"): msg += f"{len(out['pendingApproval']['places'])} places on the route have unknown hours; I can check their listings if you approve. "
        elif s.unknowns: msg += f"{len(s.unknowns)} places on the route have unknown hours. "
        return msg + "Conditions, not a safety rating."

    def result(self, sid, s, answer, by, trace, out, t0, chk) -> dict:
        return {"session": sid, "answer": answer, "by": by, "trace": trace, "ms": round((time.time() - t0) * 1000), "numbersCheck": chk,
                "preferences": (s.preferences.model_dump() if s.preferences else None), **{k: v for k, v in out.items() if k != "routes"}, "_routes": out.get("routes")}

    # ---------- no-key pipeline ----------
    async def fallback(self, text: str, s: Session, allow_checks: bool, trace: list, out: dict) -> str:
        async def run(name, args, why):
            ts = time.time(); res = await self.tool(s, name, args, out, allow_checks)
            trace.append(event(name, args, res, round((time.time() - ts) * 1000), why, ts)); return res
        wants_check = bool(re.search(r"\b(check|verify)\b", text, re.I))
        prefs = {"fewerTurns": bool(re.search(r"fewer turns|simple|simpler|straight", text, re.I)), "preferMainRoads": bool(re.search(r"main (roads?|streets?)", text, re.I)),
                 "fastest": bool(re.search(r"\bfastest\b|\bquickest\b", text, re.I)), "preferOpenPlaces": bool(re.search(r"\bopen\b|stopping|somewhere to stop", text, re.I)),
                 "lowDistraction": bool(re.search(r"low.distraction|quiet|fewer prompts", text, re.I))}
        if not (s.plan and re.search(r"^\s*(check|verify)", text, re.I)):
            m = re.search(r"from\s+(.+?)\s+to\s+(.+?)(?:\s+at\s+.+)?[.?!]*$", text, re.I) or re.search(r"(?:to|towards)\s+(.+?)[.?!]*$", text, re.I)
            if not m: return "Tell me where you're walking, for example: from Moscone Center to City Hall at 11:30 PM."
            if m.lastindex != 2: return "Where are you starting from? For example: from Moscone Center to City Hall."
            cut = lambda x: re.split(r",|;|\s+(?:and|then|but|please|at|around|by|with|tonight|today|on|this|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", x.strip(), maxsplit=1, flags=re.I)[0].strip(" .?!")
            a, b = cut(m.group(1)), cut(m.group(2))
            pa = (await run("find_place", {"query": a}, "Resolve the start on the map.")).get("candidates")
            pb = (await run("find_place", {"query": b}, "Resolve the destination on the map.")).get("candidates")
            if not pa or not pb: return f"I couldn't find {'“' + a + '”' if not pa else '“' + b + '”'} in San Francisco."
            day, minute = parse_when(text)
            res = await run("plan_routes", {"origin": {"name": pa[0]["name"], "lat": pa[0]["lat"], "lon": pa[0]["lon"]}, "destination": {"name": pb[0]["name"], "lat": pb[0]["lat"], "lon": pb[0]["lon"]},
                                            "day": day, "minute": minute}, "Score the fastest and the HootRoute routes at that time.")
            if "error" in res: return res["error"]
        if any(prefs.values()): await run("rank_by_preferences", prefs, "The request states route preferences.")
        await run("inspect_route", {"route": "recommended"}, "Check closures, empty stretches and lighting on the recommended route.")
        unk = await run("find_route_unknowns", {"route": "recommended", "limit": 4}, "Find places whose hours we don't know.")
        if unk.get("count") and wants_check:
            ids = [p["id"] for p in unk["places"]]
            if allow_checks:
                await run("check_listed_hours", {"place_ids": ids}, "The walker asked to check listed hours and approved it.")
                await run("rescore_routes", {}, "Re-score with any new evidence.")
            else:
                await run("propose_hours_check", {"place_ids": ids, "reason": "You asked to check listed hours of places with unknown hours on the route."}, "The walker asked for a check; it costs money, so ask first.")
        return self.facts_text(s, out)


def parse_when(text: str) -> tuple[int, int]:
    """'at 11:30 pm', 'friday 11 pm', 'tonight' → (day, minute); defaults to now in San Francisco."""
    now = datetime.now(SF); day, minute = now.weekday(), now.hour * 60 + now.minute
    m = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*([ap])\.?m\b", text, re.I)
    if m: minute = ((int(m.group(1)) % 12) + (12 if m.group(3).lower() == "p" else 0)) * 60 + int(m.group(2) or 0)
    for i, d in enumerate(DAYS):
        if re.search(rf"\b{d}\b", text, re.I): day = i
    return day, minute


def summarize(data: dict, routes: dict) -> dict:
    def r(x, st): return {"score": st["score"], "minutes": st["minutes"], "longest_empty_m": st["longestEmptyM"], "km": x["km"], "places_listed_open": x["places_open"],
                          "mapped_light_pct": x["light_pct"], "turns_per_km": x.get("turns_per_km"), "points": x["points"], "unknown_hours_nearby": x.get("unknown_hours_nearby")}
    out = {"recommended": r(routes["best"], data["stats"]["hootroute"]), "fastest": r(routes["fast"], data["stats"]["shortest"]),
           "same_route": routes["best"]["coords"] == routes["fast"]["coords"], "note": data.get("dataNote")}
    bal = next((o for o in data.get("options") or [] if o["id"] == "balanced"), None)
    if bal and "balanced" in routes: out["balanced"] = r(routes["balanced"], bal["stats"])
    return out


def brief(name: str, res: dict) -> str:
    if "error" in res: return res["error"]
    if name == "find_place": c = res.get("candidates") or []; return f"{len(c)} match{'es' if len(c) != 1 else ''}" + (f": {c[0]['name']}" if c else "")
    if name == "plan_routes": return f"recommended {res['recommended']['score']} vs fastest {res['fastest']['score']}, {res['recommended']['minutes']} vs {res['fastest']['minutes']} min"
    if name == "rank_by_preferences": return (res.get("choice") or {}).get("reason") or res.get("note") or "no preference applied"
    if name == "inspect_route": return f"{res['verdict']} ({sum(1 for i in res['items'] if i['level'] == 'warn')} warnings)"
    if name == "find_route_unknowns": return f"{res['count']} places with unknown hours on the route"
    if name == "propose_hours_check": return f"asked the walker to approve a check of {res.get('places')} listings ({res.get('provider')})"
    if name == "check_listed_hours":
        if res.get("note") == "declined": return "declined by the walker; nothing checked"
        counts: dict[str, int] = {}
        for x in res.get("results", []): counts[x["status"]] = counts.get(x["status"], 0) + 1
        return (", ".join(f"{v} {k}" for k, v in counts.items()) or "no results") + f"; {res.get('evidence_applied', 0)} applied" + (f", {res['reused']} reused" if res.get("reused") else "") + ("" if res.get("ok") else f" ({res.get('note')})")
    if name == "rescore_routes": return f"score {res['before']['hootroute']['score']} → {res['after']['hootroute']['score']}" + ("; route changed" if res["recommended_route_changed"] else "; route unchanged")
    if name == "replan_avoiding": return f"avoiding {res['avoiding']['radius_m']} m around {res['avoiding']['name']}: recommended {res['after']['recommended']['score']}, {res['after']['recommended']['minutes']} min"
    return "ok"
