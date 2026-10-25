"""The Head's brain: Claude reads the walker's request, delegates to the Guide (routing) and the Checker (unknown hours,
live listing checks), and explains the result. Claude chooses tools and words; it never produces a number. Every score,
time and distance in the answer comes from a tool result, and the trace records each call so a judge can verify it.

Limits: at most MAX_TOOL_CALLS tool calls and DEADLINE_S seconds per request; malformed tool arguments are rejected
before they reach the engine; with no ANTHROPIC_API_KEY a fixed pipeline runs instead and says so.
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

from . import hours_check
from .brand import BRAND
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


# ------------------------------------------------------------------------------------------------ tools
POINT = {"type": "object", "properties": {"name": {"type": "string"}, "lat": {"type": "number"}, "lon": {"type": "number"}}, "required": ["name", "lat", "lon"]}
TOOLS = [
    {"name": "find_place", "description": "Guide: look up a place, landmark or street in San Francisco. Returns candidates with coordinates. Use before plan_routes for any named place.",
     "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
    {"name": "plan_routes", "description": "Guide: plan and score the fastest walking route and the HootRoute route between two points at a departure time. "
     "Scores (0-100) come from a deterministic engine: listed-open places, gaps between them, help points, mapped lighting, main roads, transit running, turns. No crime data.",
     "input_schema": {"type": "object", "properties": {"origin": POINT, "destination": POINT, "day": {"type": "integer", "minimum": 0, "maximum": 6, "description": "0 = Monday"},
                                                       "minute": {"type": "integer", "minimum": 0, "maximum": 1439, "description": "minutes after midnight, San Francisco time"}},
                      "required": ["origin", "destination", "day", "minute"]}},
    {"name": "find_route_unknowns", "description": "Checker: list named places right on the planned route whose opening hours are unknown. Unknown hours count as closed in the score, so they can hide open places.",
     "input_schema": {"type": "object", "properties": {"route": {"type": "string", "enum": ["recommended", "fastest"]}, "limit": {"type": "integer", "minimum": 1, "maximum": 6}}, "required": ["route"]}},
    {"name": "check_listed_hours", "description": "Checker: run a live Apify Google Maps check on the published listings of places returned by find_route_unknowns (takes 30-90 s, costs a few cents). "
     "Found hours become evidence for the engine. A listing is not proof a place is staffed.",
     "input_schema": {"type": "object", "properties": {"place_ids": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 6}}, "required": ["place_ids"]}},
    {"name": "rescore_routes", "description": "Guide: plan the same walk again with any new hours evidence and report before/after scores and whether the recommended route changed.",
     "input_schema": {"type": "object", "properties": {}}},
]
AGENT_OF = {"find_place": "guide", "plan_routes": "guide", "find_route_unknowns": "checker", "check_listed_hours": "checker", "rescore_routes": "guide"}


def system_prompt(now: datetime, session: dict | None, allow_checks: bool) -> str:
    cur = (f"\nThe walker already has a plan in this conversation: {session['origin']['name']} → {session['destination']['name']}, "
           f"{DAYS[session['day']]} at {session['minute'] // 60 % 24:02d}:{session['minute'] % 60:02d}. Use find_route_unknowns / check_listed_hours / rescore_routes on it unless they ask for a different walk.") if session else ""
    return f"""You are the Head of {BRAND}, a walking companion for San Francisco late-shift workers (hospitality, service and healthcare staff) walking after dark.
You coordinate three agents through tools: the Guide (find_place, plan_routes, rescore_routes) and the Checker (find_route_unknowns, check_listed_hours).
It is now {DAYS[now.weekday()]} {now.strftime('%-I:%M %p')} in San Francisco (day {now.weekday()}, minute {now.hour * 60 + now.minute}). If no time is given, plan for now.
{cur}
How to work:
1. Resolve places with find_place, then plan_routes. 2. Call find_route_unknowns on the recommended route.
3. {"If unknown hours could matter (the walker asks for open places, or the route has a long empty stretch), call check_listed_hours on up to 4 of them, then rescore_routes." if allow_checks else "Do NOT call check_listed_hours in this request; say the walker can ask you to check listed hours."}
4. Answer in at most 5 short sentences of plain text (no headings, no bullet lists), saying times as clock times like 11:30 PM: which route and why, the numbers from the tools (score, minutes, longest empty stretch), what the check found and whether anything changed. If nothing changed, say so.

Rules: every number you state must come from a tool result. Unknown hours are unknown, not closed and not a risk. A listing is not proof a place is staffed.
Say "conditions, not a safety rating" once. Never use the words safe, unsafe, dangerous or sketchy. Never suggest calling 911 is automatic; {BRAND} never calls 911.
If a place is outside San Francisco or cannot be found, say so and ask for another place."""


class Session:
    """One walker's planning conversation (PWA tab or ASI:One chat)."""
    def __init__(self):
        self.plan: dict | None = None; self.routes: dict | None = None; self.req: dict | None = None; self.unknowns: list = []; self.ts = time.time()
        self.history: list[dict] = []      # text-only turns, so a follow-up ("check those hours") keeps its context


class HeadBrain:
    def __init__(self, port, engine):
        self.port, self.engine = port, engine; self.sessions: dict[str, Session] = {}

    def session(self, sid: str | None) -> tuple[str, Session]:
        now = time.time(); self.sessions = {k: v for k, v in self.sessions.items() if now - v.ts < 3600}
        sid = sid or uuid.uuid4().hex[:12]; s = self.sessions.setdefault(sid, Session()); s.ts = now; return sid, s

    # ---------- tool implementations ----------
    async def tool(self, s: Session, name: str, args: dict, out: dict) -> dict:
        if name == "find_place":
            q = str(args.get("query", ""))[:80]
            hits = await asyncio.to_thread(self.engine.search, q, 5)
            return {"candidates": hits} if hits else {"candidates": [], "note": "No match in the San Francisco map. Try a landmark, a street or a business name."}
        if name == "plan_routes":
            o, d = args["origin"], args["destination"]
            for p in (o, d):
                if not (37.6 <= float(p["lat"]) <= 37.9 and -122.6 <= float(p["lon"]) <= -122.3): return {"error": f"{p['name']} is outside San Francisco"}
            day, minute = int(args["day"]) % 7, int(args["minute"]) % 1440
            try: data, routes = await self.port.plan(o, d, day, minute, "Walker", "Guardian")
            except ValueError as e: return {"error": str(e)}
            s.plan, s.routes, s.req = data, routes, {"origin": o, "destination": d, "day": day, "minute": minute}; s.unknowns = []
            out["before"] = data["stats"]; out["plan"] = data; out["routes"] = routes; out["req"] = s.req
            return summarize(data, routes)
        if not s.plan: return {"error": "No walk planned yet. Call plan_routes first."}
        if name == "find_route_unknowns":
            key = "fast" if args.get("route") == "fastest" else "best"; limit = max(1, min(6, int(args.get("limit", 5))))
            s.unknowns = await asyncio.to_thread(hours_check.unknowns, self.engine, s.routes[key]["coords"], s.req["day"], s.req["minute"], limit)
            out["unknowns"] = s.unknowns
            return {"places": [{k: p[k] for k in ("id", "name", "cat", "atM", "passMinute")} for p in s.unknowns], "count": len(s.unknowns),
                    "route_unknown_total": s.routes[key].get("unknown_hours_nearby")}
        if name == "check_listed_hours":
            ids = [str(i) for i in args.get("place_ids", [])][:6]; known = {p["id"]: p for p in s.unknowns}
            places = [known[i] for i in ids if i in known]
            if not places: return {"error": "Only places returned by find_route_unknowns can be checked."}
            res = await asyncio.to_thread(hours_check.check, places)
            res["changed"] = await asyncio.to_thread(hours_check.apply, self.engine, res["results"]) if res["ok"] else 0
            out["check"] = res
            return {"ok": res["ok"], "note": res["note"], "evidence_applied": res["changed"], "seconds": (res.get("run") or {}).get("seconds"),
                    "results": [{k: r.get(k) for k in ("name", "status", "hours", "source")} for r in res["results"]]}
        if name == "rescore_routes":
            before = s.plan["stats"]; old_best = s.routes["best"]["coords"]; q = s.req
            data, routes = await self.port.plan(q["origin"], q["destination"], q["day"], q["minute"], "Walker", "Guardian")
            s.plan, s.routes = data, routes
            out["after"] = data["stats"]; out["plan"] = data; out["routes"] = routes; out["routeChanged"] = routes["best"]["coords"] != old_best
            return {"before": before, "after": data["stats"], "recommended_route_changed": out["routeChanged"]}
        return {"error": f"unknown tool {name}"}

    # ---------- entry point ----------
    async def ask(self, text: str, sid: str | None = None, allow_checks: bool = True, history: list[dict] | None = None) -> dict:
        sid, s = self.session(sid); t0 = time.time(); trace: list[dict] = []; out: dict = {}
        prior = s.req
        if not enabled():
            ans = await self.fallback(text, s, allow_checks, trace, out)
            return self.result(sid, ans, f"fixed pipeline (Claude not configured)", trace, out, t0)
        now = datetime.now(SF)
        msgs = (list(history) if history else list(s.history))[-8:] + [{"role": "user", "content": text[:1000]}]
        sysmsg = system_prompt(now, prior, allow_checks)
        tools = [t for t in TOOLS if allow_checks or t["name"] != "check_listed_hours"]
        answer = ""; calls = 0
        try:
            while True:
                r = await claude(msgs, sysmsg, tools)
                blocks = r.get("content", []); msgs.append({"role": "assistant", "content": blocks})
                uses = [b for b in blocks if b.get("type") == "tool_use"]
                if not uses or r.get("stop_reason") != "tool_use":
                    answer = "".join(b.get("text", "") for b in blocks if b.get("type") == "text").strip(); break
                results = []
                for u in uses:
                    calls += 1; ts = time.time()
                    if calls > MAX_TOOL_CALLS or time.time() - t0 > DEADLINE_S:
                        res = {"error": "Tool budget reached. Answer with what you have."}
                    else:
                        try: res = await self.tool(s, u["name"], u.get("input") or {}, out)
                        except (KeyError, TypeError, ValueError) as e: res = {"error": f"Invalid arguments: {e}"}
                    trace.append({"agent": AGENT_OF.get(u["name"], "head"), "tool": u["name"], "input": u.get("input"), "ok": "error" not in res and res.get("ok", True) is not False,
                                  "ms": round((time.time() - ts) * 1000), "summary": brief(u["name"], res)})
                    results.append({"type": "tool_result", "tool_use_id": u["id"], "content": json.dumps(res)[:6000]})
                msgs.append({"role": "user", "content": results})
                if calls > MAX_TOOL_CALLS + 2: break
        except Exception as e:
            log.warning("Claude orchestration failed: %s", e)
            if not out.get("plan"):
                ans = await self.fallback(text, s, allow_checks, trace, out)
                return self.result(sid, ans, f"fixed pipeline (Claude error: {type(e).__name__})", trace, out, t0)
            answer = answer or "I planned the walk but could not finish the explanation. The numbers below come from the engine."
        answer = clean(answer)
        s.history += [{"role": "user", "content": text[:1000]}, {"role": "assistant", "content": answer or "(no answer)"}]
        return self.result(sid, answer, f"Claude ({model()})", trace, out, t0)

    def result(self, sid, answer, by, trace, out, t0) -> dict:
        return {"session": sid, "answer": answer, "by": by, "trace": trace, "ms": round((time.time() - t0) * 1000), **{k: v for k, v in out.items() if k != "routes"},
                "_routes": out.get("routes")}

    # ---------- no-key pipeline ----------
    async def fallback(self, text: str, s: Session, allow_checks: bool, trace: list, out: dict) -> str:
        async def run(name, args):
            ts = time.time(); res = await self.tool(s, name, args, out)
            trace.append({"agent": AGENT_OF[name], "tool": name, "input": args, "ok": "error" not in res and res.get("ok", True) is not False, "ms": round((time.time() - ts) * 1000), "summary": brief(name, res)}); return res
        wants_check = bool(re.search(r"\bcheck|verify|open\b", text, re.I))
        if not (s.plan and re.search(r"^\s*(check|verify)", text, re.I)):
            m = re.search(r"from\s+(.+?)\s+to\s+(.+?)(?:\s+at\s+.+)?[.?!]*$", text, re.I) or re.search(r"(?:to|towards)\s+(.+?)[.?!]*$", text, re.I)
            if not m: return "Tell me where you're walking, for example: from Moscone Center to City Hall."
            a, b = (m.group(1), m.group(2)) if m.lastindex == 2 else ("Moscone Center", m.group(1))
            cut = lambda x: re.split(r",|;|\s+(?:and|then|but|please|at|around|by)\s+", x.strip(), maxsplit=1)[0].strip(" .?!")
            a, b = cut(a), cut(b)
            pa, pb = (await run("find_place", {"query": a})).get("candidates"), (await run("find_place", {"query": b})).get("candidates")
            if not pa or not pb: return f"I couldn't find {'“' + a + '”' if not pa else '“' + b + '”'} in San Francisco."
            now = datetime.now(SF)
            res = await run("plan_routes", {"origin": {"name": pa[0]["name"], "lat": pa[0]["lat"], "lon": pa[0]["lon"]}, "destination": {"name": pb[0]["name"], "lat": pb[0]["lat"], "lon": pb[0]["lon"]},
                                            "day": now.weekday(), "minute": now.hour * 60 + now.minute})
            if "error" in res: return res["error"]
        unk = await run("find_route_unknowns", {"route": "recommended", "limit": 4})
        st = s.plan["stats"]; msg = (f"HootRoute route: score {st['streetwise']['score']} vs {st['shortest']['score']} for the fastest, {st['streetwise']['minutes']} vs {st['shortest']['minutes']} min, "
                                     f"longest empty stretch {st['streetwise']['longestEmptyM']} m vs {st['shortest']['longestEmptyM']} m. ")
        if unk.get("count") and allow_checks and wants_check:
            chk = await run("check_listed_hours", {"place_ids": [p["id"] for p in unk["places"]]})
            after = await run("rescore_routes", {})
            msg += f"Checked {len(chk.get('results', []))} listings: {chk.get('evidence_applied', 0)} added hours. Score now {after['after']['streetwise']['score']} (was {after['before']['streetwise']['score']}). "
        elif unk.get("count"):
            msg += f"{unk['count']} places on the route have unknown hours; ask me to check their listings. "
        return msg + "Conditions, not a safety rating."


def summarize(data: dict, routes: dict) -> dict:
    def r(x, st): return {"score": st["score"], "minutes": st["minutes"], "longest_empty_m": st["longestEmptyM"], "km": x["km"], "places_listed_open": x["places_open"],
                          "mapped_light_pct": x["light_pct"], "points": x["points"], "unknown_hours_nearby": x.get("unknown_hours_nearby")}
    return {"recommended": r(routes["best"], data["stats"]["streetwise"]), "fastest": r(routes["fast"], data["stats"]["shortest"]),
            "same_route": routes["best"]["coords"] == routes["fast"]["coords"], "note": data.get("dataNote")}


def brief(name: str, res: dict) -> str:
    if "error" in res: return res["error"]
    if name == "find_place": c = res.get("candidates") or []; return f"{len(c)} match{'es' if len(c) != 1 else ''}" + (f": {c[0]['name']}" if c else "")
    if name == "plan_routes": return f"recommended {res['recommended']['score']} vs fastest {res['fastest']['score']}, {res['recommended']['minutes']} vs {res['fastest']['minutes']} min"
    if name == "find_route_unknowns": return f"{res['count']} places with unknown hours on the route"
    if name == "check_listed_hours":
        counts: dict[str, int] = {}
        for x in res.get("results", []): counts[x["status"]] = counts.get(x["status"], 0) + 1
        return (", ".join(f"{v} {k}" for k, v in counts.items()) or "no results") + f"; {res.get('evidence_applied', 0)} applied" + ("" if res.get("ok") else f" ({res.get('note')})")
    if name == "rescore_routes": return f"score {res['before']['streetwise']['score']} → {res['after']['streetwise']['score']}" + ("; route changed" if res["recommended_route_changed"] else "; route unchanged")
    return "ok"
