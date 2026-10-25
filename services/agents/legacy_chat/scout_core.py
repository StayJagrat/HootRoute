"""Scout's brain, free of any uAgents plumbing so test_local.py and the chat handler share exactly the same code.

Flow: parse request -> engine /api/route -> (optional) ask shop agents about places in the empty stretch ->
engine /api/agents/place/declare re-scores -> text summary. The score is always the engine's; nothing here computes it.
"""
from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from common import DAY_NAMES, Engine, fmt_minute
from models import HoursReply
from parser import Parsed, llm_extract, looks_like_route_request, parse_request

WALK_SPEED = 1.35   # m/s, only used to turn "metres along the route" into the minute a shop is passed (same constant as the engine)
AskPlace = Callable[[str, str, int, int], Awaitable[HoursReply | None]]   # (place_id, name, day, pass_minute)

REASONS = {"places": "more open places along the way", "gaps": "shorter empty stretches", "help": "help points within reach",
           "light": "better-lit streets", "main": "more main streets", "transit": "BART running nearby", "turns": "fewer turns"}

HELP = ("I am **Streetwise Scout**. Tell me where you are walking and when, and I score the fastest route against the Streetwise route "
        "at the minute you pass each block (open places, empty stretches, help points, street lighting, BART running, turns).\n\n"
        "Try: *Walk me from Powell BART to Civic Center at 11:40pm*\n\n"
        "Then: **start walk** (I check in with you and hand off to my rescuer if you stop replying), **ok** (reply to a check-in), "
        "**stop walk**, **report broken light near Civic Center BART** (I draft a 311 report, never submit it), **audit**.")


@dataclass
class PlanResult:
    ok: bool
    text: str
    plan: dict = field(default_factory=dict)       # saved so a follow-up 'start walk' knows the route
    confirmed: list[dict] = field(default_factory=list)
    events: list[str] = field(default_factory=list)


def _reason(fast: dict, best: dict) -> str:
    d = sorted(((best["points"][k] - fast["points"][k], k) for k in best["points"]), reverse=True)
    ups = [f"{REASONS[k]} (+{v:.1f})" for v, k in d if v >= 0.5 and k in REASONS][:3]
    downs = [f"{REASONS[k].split(' along')[0]} ({v:.1f})" for v, k in reversed(d) if v <= -0.5 and k in REASONS][:1]
    s = "It gains " + ", ".join(ups) if ups else "It scores higher overall"
    if downs: s += f", at a small cost in {downs[0]}"
    return s + "."


def _row(label: str, f, b) -> str: return f"| {label} | {f} | {b} |"


def _table(fast: dict, best: dict | None) -> str:
    rows = ["| | Fastest | Streetwise |", "|---|---|---|"] if best else ["| | Route |", "|---|---|"]
    items = [("Score (0-100)", lambda r: f"**{r['score']:.1f}**"), ("Walking time", lambda r: f"{r['minutes']:.1f} min ({r['km']} km)"),
             ("Longest empty stretch", lambda r: f"{r['gap']['m']} m"), ("Open places on the way", lambda r: str(r["places_open"])),
             ("Lit street", lambda r: f"{r['light_pct']}%")]
    for lab, fn in items: rows.append(_row(lab, fn(fast), fn(best)) if best else f"| {lab} | {fn(fast)} |")
    return "\n".join(rows)


async def plan_walk(text: str, session: str, engine: Engine, ask_place: AskPlace | None, known_places: set[str] | None = None,
                    cached_decl: Callable[[str, int], int | None] | None = None, now=None) -> PlanResult:
    ev: list[str] = []
    try:
        landmarks = await engine.landmarks()
    except Exception as e:
        return PlanResult(False, f"I cannot reach the Streetwise engine right now ({type(e).__name__}). Please try again in a moment.")
    parsed = parse_request(text, landmarks, now=now)
    if not parsed.ok and not parsed.origin_text and not parsed.dest_text and os.environ.get("ASI1_API_KEY"):
        parsed = parse_request(text, landmarks, now=now, llm=await llm_extract(text, [l["name"] for l in landmarks]))
    elif not parsed.ok and os.environ.get("ASI1_API_KEY"):
        llm = await llm_extract(text, [l["name"] for l in landmarks])
        if llm: parsed = parse_request(text, landmarks, now=now, llm=llm)
    if not parsed.ok:
        return PlanResult(False, "\n".join(parsed.errors) + "\n\n" + HELP)

    fixed = os.environ.get("SCOUT_FIXED_SESSION", "").strip()
    if fixed:
        session = fixed; await engine.reset(session)       # same session the PWA trace panel watches; start clean every request
    o, d = (parsed.origin.lat, parsed.origin.lon), (parsed.dest.lat, parsed.dest.lon)
    try:
        out = await engine.route(session, o, d, parsed.day, parsed.minute)
    except Exception as e:
        return PlanResult(False, f"The engine could not plan that walk ({type(e).__name__}: {e}).")
    routes = {r["id"]: r for r in out["routes"]}; fast = routes["fast"]; best = routes.get("best")
    ev.append(f"engine: fast {fast['score']}" + (f", best {best['score']}" if best else ""))
    confirmed: list[dict] = []; notes: list[str] = list(parsed.notes); attempts: list[str] = []
    before = {k: v["score"] for k, v in routes.items()}; after = dict(before); final_routes = routes

    # --- shop agents: ask the ones that sit in the empty stretch of the fastest route ---
    if known_places:
        try: suggestions = await engine.suggest(session)
        except Exception: suggestions = []
        for s in suggestions:
            if s["id"] not in known_places: continue
            pass_min = int(parsed.minute + s["at"] / WALK_SPEED / 60)
            until = cached_decl(s["id"], pass_min) if cached_decl else None
            via = "declared earlier"
            if until is None and ask_place:
                rep = await ask_place(s["id"], s["name"], parsed.day, pass_min); via = "answered my query"
                if rep is None: attempts.append(f"{s['name']}: no reply from its agent"); continue
                if not rep.open_at_minute or rep.open_until is None: attempts.append(f"{s['name']}: agent says it is closed at {fmt_minute(pass_min)}"); continue
                until = rep.open_until; sim = rep.simulated
            else: sim = True
            if until is None: continue
            try: dec = await engine.declare(session, s["id"], until, parsed.day, parsed.minute)
            except Exception as e: attempts.append(f"{s['name']}: engine declare failed ({type(e).__name__})"); continue
            prev = dict(after)
            if dec.get("route"):
                final_routes = {r["id"]: r for r in dec["route"]["routes"]}; after = {k: v["score"] for k, v in final_routes.items()}
            confirmed.append(dict(id=s["id"], name=s["name"], cat=s["cat"], until=until, pass_minute=pass_min, simulated=sim, via=via, prev=prev, now=dict(after)))
            ev.append(f"{s['name']} confirmed open until {fmt_minute(until)}; engine re-scored: {after}")

    fast2 = final_routes["fast"]; best2 = final_routes.get("best")
    head = f"**{parsed.origin.name} to {parsed.dest.name}**, {DAY_NAMES[(parsed.day + parsed.minute // 1440) % 7]} {fmt_minute(parsed.minute)}"
    lines = [head, "", _table(fast2, best2), ""]
    if best2:
        gain = best2["score"] - fast2["score"]; extra = best2["minutes"] - fast2["minutes"]
        lines.append(f"**Recommendation: the Streetwise route** scores {best2['score']:.1f} against {fast2['score']:.1f} for the fastest "
                     f"({gain:+.1f} points for {extra:+.1f} min). {_reason(fast2, best2)} Longest empty stretch: {fast2['gap']['m']} m on the fastest, {best2['gap']['m']} m on the Streetwise route.")
    else:
        lines.append(f"**Recommendation: the fastest route**, which is also the best-scoring one ({fast2['score']:.1f}). Longest empty stretch: {fast2['gap']['m']} m.")
    names = [s["name"] for s in (best2 or fast2)["shops"]]
    if names: lines.append("Open on this route at the time you pass: " + ", ".join(names[:6]) + ("." if len(names) <= 6 else f" and {len(names) - 6} more."))
    for c in confirmed:
        tag = " (simulated demo shop agent)" if c["simulated"] else ""
        chg = "; ".join(f"{('Streetwise' if k == 'best' else 'Fastest')} route {c['prev'][k]:.1f} to {c['now'][k]:.1f} ({c['now'][k] - c['prev'][k]:+.1f})" for k in c["now"] if k in c["prev"])
        lines.append(f"\n**Shop agent confirmed:** {c['name']}'s agent{tag} {c['via']} and confirmed it is open until {fmt_minute(c['until'])}, "
                     f"so the engine re-scored the walk: {chg}.")
    if len(confirmed) > 1:
        tot = "; ".join(f"{('Streetwise' if k == 'best' else 'Fastest')} route {before[k]:.1f} to {after[k]:.1f} ({after[k] - before[k]:+.1f})" for k in after if k in before)
        lines.append(f"\n**Total after {len(confirmed)} shop agents:** {tot}.")
    if attempts: lines.append("\nShop agents asked but not confirmed: " + "; ".join(attempts) + ".")
    if notes: lines.append("\n_" + " ".join(notes) + "_")
    lines.append("\nReply **start walk** and I will check in with you along the way.")
    plan = dict(label=f"{parsed.origin.name} to {parsed.dest.name}", destination=parsed.dest.name, session=session,
                minutes=(best2 or fast2)["minutes"], coords=(best2 or fast2)["coords"], day=parsed.day, minute=parsed.minute,
                scores=dict(fast=fast2["score"], best=best2["score"] if best2 else None))
    return PlanResult(True, "\n".join(lines), plan, confirmed, ev)


def card_for(result: PlanResult, final: dict | None = None):
    """Optional Interactive Card (carousel). Built with the helpers in the installed uagents_core; returns a MetadataContent."""
    from uagents_core.contrib.protocols.chat.cards import CarouselCardPayload, CarouselItem, CtaAction, CarouselBadge, create_card_content
    p = result.plan; s = p["scores"]
    items = [CarouselItem(id="best", title=f"Streetwise route {s['best']:.1f}" if s["best"] else f"Fastest route {s['fast']:.1f}", subtitle=p["label"],
                          secondary_text=f"{p['minutes']:.0f} min walk", badges=[CarouselBadge(label="Recommended", variant="success")],
                          primary_cta=CtaAction(label="Start walk", selection={"action": "start_walk"}, primary=True))]
    if s["best"]:
        items.append(CarouselItem(id="fast", title=f"Fastest route {s['fast']:.1f}", subtitle=p["label"], secondary_text="Shortest, lower score",
                                  primary_cta=CtaAction(label="Start walk", selection={"action": "start_walk"})))
    return create_card_content(CarouselCardPayload(title="Your walk", subtitle=p["label"], items=items), card_id=uuid.uuid4())
