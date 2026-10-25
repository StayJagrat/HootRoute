"""scout: the front-door agent. Speaks the Agent Chat Protocol, so it is discoverable and usable in ASI:One.

Run alone:  python scout.py
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from uuid import uuid4

from uagents import Context, Protocol
from uagents_core.contrib.protocols.chat import (ChatAcknowledgement, ChatMessage, EndSessionContent, MetadataContent, StartSessionContent,
                                                 TextContent, chat_protocol_spec)

from common import CORE, Engine, address_of, load_places, make_agent, mode
from models import (AuditReport, AuditRequest, CheckInAck, HoursDeclaration, HoursQuery, HoursReply, ReportDraft, ReportRequest, UserNotice,
                    WalkStart, WalkStop)
from parser import resolve
from scout_core import HELP, PlanResult, card_for, plan_walk


def _now(): return datetime.now(timezone.utc)


def _chat(text: str, end: bool = True, extra=None) -> ChatMessage:
    content = [TextContent(type="text", text=text)] + list(extra or [])
    if end: content.append(EndSessionContent(type="end-session"))
    return ChatMessage(timestamp=_now(), msg_id=uuid4(), content=content)


def _get(ctx: Context, key: str):
    v = ctx.storage.get(key)
    try: return json.loads(v) if v else None
    except Exception: return None


def _put(ctx: Context, key: str, val): ctx.storage.set(key, json.dumps(val))


def build_scout():
    agent = make_agent(CORE["scout"]["name"], CORE["scout"]["seed_env"], CORE["scout"]["port"], "scout.md")
    chat = Protocol(spec=chat_protocol_spec)
    engine = Engine()
    place_addr = {}
    for p in load_places():
        try: place_addr[p["place_id"]] = address_of("place:" + p["place_id"])
        except RuntimeError as e: print(f"[scout] shop agent {p['name']} skipped: {e}")      # scout still works without it
    def trusted_relays():
        out = set()
        for k in ("watcher", "rescuer"):
            try: out.add(address_of(k))
            except RuntimeError: pass
        return out
    ask_timeout = int(os.environ.get("PLACE_ASK_TIMEOUT_S", "10"))

    # ---------- command handling -------------------------------------------------------------------------------
    async def handle_text(ctx: Context, sender: str, text: str) -> tuple[str, PlanResult | None]:
        t = text.strip(); low = t.lower().strip(" .!?")
        walk = _get(ctx, f"walk:{sender}")
        if not t or low in {"help", "hi", "hello", "hey", "?"}: return HELP, None
        if re.match(r"^(start|begin)( the| my)?( walk|walking)?$", low): return await start_walk(ctx, sender), None
        if re.match(r"^(stop|end|cancel)( the| my)?( walk|walking| check-?ins?)?$|^(i'?m|i am)( home| there| here| arrived|)( safe)?$|^arrived$", low) and walk:
            await ctx.send(address_of("watcher"), WalkStop(session=walk["session"], user=sender)); _put(ctx, f"walk:{sender}", None)
            return "Walk ended. I stopped checking in.", None
        if walk and re.match(r"^(ok|okay|safe|i'?m ok|i am ok|i'?m okay|i'?m safe|all good|fine|here|yes|y|good)$", low):
            await ctx.send(address_of("watcher"), CheckInAck(session=walk["session"], user=sender)); return "Thanks, checked in. I will ask again later.", None
        if low.startswith("report"): return await report(ctx, sender, t), None
        if re.match(r"^(night )?audit\b", low): return await audit(ctx), None
        res = await plan_walk(t, session=f"asi-{sender[-8:]}-{uuid4().hex[:6]}", engine=engine, ask_place=make_asker(ctx), known_places=set(place_addr),
                              cached_decl=lambda pid, minute: cached(ctx, pid, minute))
        if res.ok: _put(ctx, f"plan:{sender}", res.plan)
        return res.text, res

    def make_asker(ctx: Context):
        async def ask(place_id: str, name: str, day: int, minute: int):
            rep, status = await ctx.send_and_receive(place_addr[place_id], HoursQuery(place_id=place_id, day=day, minute=minute), response_type=HoursReply, timeout=ask_timeout)
            if isinstance(rep, HoursReply) and rep.place_id == place_id: return rep
            ctx.logger.info(f"no usable answer from shop agent for {name}: {status}"); return None
        return ask

    def cached(ctx: Context, place_id: str, minute: int):
        d = _get(ctx, f"decl:{place_id}")
        return d["until"] if d and d["until"] >= minute else None

    async def start_walk(ctx: Context, sender: str) -> str:
        plan = _get(ctx, f"plan:{sender}")
        if not plan: return "Plan a walk first, for example: Walk me from Powell BART to Civic Center at 11:40pm."
        every = int(os.environ.get("WATCH_CHECK_EVERY_S", "300")); deadline = int(os.environ.get("WATCH_REPLY_DEADLINE_S", "120"))
        await ctx.send(address_of("watcher"), WalkStart(session=plan["session"], user=sender, label=plan["label"], expected_minutes=plan["minutes"], check_every_s=every,
                                                       reply_deadline_s=deadline, route_coords=plan["coords"], destination=plan["destination"]))
        _put(ctx, f"walk:{sender}", dict(session=plan["session"]))
        return (f"Walk started: {plan['label']} (about {plan['minutes']:.0f} min). My watcher will check in about every {every // 60 or 1} min. Reply **ok** each time. "
                f"If you stop replying for {deadline}s, my rescuer prepares a handoff packet for your trusted contact. It never contacts emergency services. If you need emergency help, call 911 yourself. "
                "Say **stop walk** when you arrive.")

    async def report(ctx: Context, sender: str, text: str) -> str:
        m = re.match(r"^report\s+(?:a\s+|an\s+|the\s+)?(.+?)\s+(?:near|at|by|on|around|outside)\s+(.+)$", text.strip(), re.I)
        issue, where = (m.group(1), m.group(2)) if m else (re.sub(r"^report\s+", "", text, flags=re.I), "")
        pt = None
        if where:
            try: pt, _ = resolve(where, await engine.landmarks())
            except Exception: pt = None
        req = ReportRequest(session=sender[-8:], user=sender, issue=issue, place_label=pt.name if pt else where or "unspecified location",
                            lat=pt.lat if pt else None, lon=pt.lon if pt else None)
        rep, status = await ctx.send_and_receive(address_of("reporter"), req, response_type=ReportDraft, timeout=15)
        if not isinstance(rep, ReportDraft): return f"My reporter agent did not answer ({status}). Nothing was drafted."
        return f"I drafted a 311 report. **It is a DRAFT: nothing has been submitted.** Review it and submit it yourself at 311 (sf311.org).\n\n```\n{rep.text}\n```\nSaved to {rep.path}"

    async def audit(ctx: Context) -> str:
        rep, status = await ctx.send_and_receive(address_of("night_auditor"), AuditRequest(session="auditor"), response_type=AuditReport, timeout=30)
        return rep.summary if isinstance(rep, AuditReport) else f"The night auditor did not answer ({status})."

    # ---------- Agent Chat Protocol ------------------------------------------------------------------------------
    @chat.on_message(ChatMessage)
    async def on_chat(ctx: Context, sender: str, msg: ChatMessage):
        await ctx.send(sender, ChatAcknowledgement(timestamp=_now(), acknowledged_msg_id=msg.msg_id))      # always ack first
        texts, card_action = [], None
        for item in msg.content:
            if isinstance(item, TextContent): texts.append(item.text)
            elif isinstance(item, MetadataContent):
                try:
                    from uagents_core.contrib.protocols.chat.cards import extract_card_response
                    r = extract_card_response(item)
                    if r and r.selection and r.selection.get("action") == "start_walk": card_action = "start walk"
                except Exception: pass
            elif isinstance(item, StartSessionContent) and not texts: texts.append("help")
        text = card_action or " ".join(texts).strip()
        if not text and not any(isinstance(i, (TextContent, MetadataContent)) for i in msg.content): return    # nothing for us in this message
        try:
            reply, res = await handle_text(ctx, sender, text)
            extra = []
            if res and res.ok and os.environ.get("SCOUT_CARDS") == "1":
                try: extra.append(card_for(res))
                except Exception as e: ctx.logger.warning(f"card skipped: {e}")
            await ctx.send(sender, _chat(reply, end=not extra, extra=extra))
        except Exception as e:
            ctx.logger.exception("scout failed")
            await ctx.send(sender, _chat(f"Sorry, something went wrong on my side ({type(e).__name__}). Please try again."))

    @chat.on_message(ChatAcknowledgement)
    async def on_ack(ctx: Context, sender: str, msg: ChatAcknowledgement):
        ctx.logger.debug(f"ack from {sender} for {msg.acknowledged_msg_id}")      # never reply to acks

    agent.include(chat, publish_manifest=(mode() != "local"))

    # ---------- typed agent-to-agent messages --------------------------------------------------------------------
    @agent.on_message(HoursDeclaration)
    async def on_declaration(ctx: Context, sender: str, msg: HoursDeclaration):
        if place_addr.get(msg.place_id) != sender:
            ctx.logger.warning(f"ignoring declaration for {msg.place_id} from untrusted sender {sender}"); return
        _put(ctx, f"decl:{msg.place_id}", dict(until=msg.open_until, sender=sender))
        ctx.logger.info(f"{msg.name} declared open until minute {msg.open_until}")

    @agent.on_message(UserNotice)
    async def on_notice(ctx: Context, sender: str, msg: UserNotice):
        if sender not in trusted_relays(): ctx.logger.warning(f"ignoring notice from {sender}"); return
        await ctx.send(msg.user, _chat(msg.text, end=False))

    return agent


if __name__ == "__main__":
    a = build_scout(); print(f"scout address: {a.address}"); a.run()
