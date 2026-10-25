"""hootroute-head: the HootRoute Head on Agentverse, usable entirely inside an ASI:One chat (Agent Chat Protocol).

The whole primary workflow runs in the conversation: the walker describes the walk, Professor Hoot (Claude) has Scoot McRoute
plan and score the routes and Sherlock Hoots look for places with unknown hours. A paid listing check is only proposed;
the walker answers "approve" (or "skip") in the chat, then the check runs and the walk is re-scored. "Start my walk" creates
a real walk and returns the walker and guardian links.

    python head_chat.py        # alone (prints the Agentverse inspector link to connect the mailbox)
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from uuid import uuid4

import httpx
from uagents import Context, Protocol
from uagents_core.contrib.protocols.chat import ChatAcknowledgement, ChatMessage, EndSessionContent, StartSessionContent, TextContent, chat_protocol_spec

from common import CORE, ENGINE_URL, make_agent, mode

HELP = ("Hi, I'm Professor Hoot from HootRoute, a journey companion for people walking in San Francisco after dark.\n\n"
        "Tell me your walk, for example: **My shift ends at 11:30 PM near Moscone Center, walk me to City Hall, I'd like more places open.**\n"
        "Scoot McRoute scores the fastest route and alternatives, and Sherlock Hoots looks for places whose hours are unknown. "
        "If a live listing check could help, I'll ask first (it costs a few cents): answer **approve** or **skip**. "
        "Then say **start my walk** (you get a walker link and a link for the person watching over you).\n\n"
        "Scores describe route conditions, not a safety rating. HootRoute never calls 911.")


def _now(): return datetime.now(timezone.utc)


def _chat(text: str, end: bool = True) -> ChatMessage:
    content = [TextContent(type="text", text=text)]
    if end: content.append(EndSessionContent(type="end-session"))
    return ChatMessage(timestamp=_now(), msg_id=uuid4(), content=content)


async def _post(path: str, body: dict, timeout: float = 240) -> dict:
    async with httpx.AsyncClient(timeout=timeout) as c:
        r = await c.post(ENGINE_URL + path, json=body); r.raise_for_status(); return r.json()


def _trace(res: dict) -> str:
    lines = [f"- **{t.get('persona') or t['agent'].capitalize()}** · {t['tool'].replace('_', ' ')} · {t['summary']}" for t in res.get("trace", [])]
    return ("\n\n_Agent activity:_\n" + "\n".join(lines)) if lines else ""


def build_head():
    c = CORE["head"]; agent = make_agent(c["name"], c["seed_env"], c["port"], "head.md")
    chat = Protocol(spec=chat_protocol_spec)
    public = os.environ.get("PUBLIC_URL", "").rstrip("/")

    async def handle(ctx: Context, sender: str, text: str) -> str:
        low = text.lower().strip(" .!?")
        if not low or low in {"help", "hi", "hello", "hey", "?"}: return HELP
        sid = ctx.storage.get(f"session:{sender}")
        if re.match(r"^(start|begin)( the| my)?( walk|walking)?\b", low):
            plan = ctx.storage.get(f"plan:{sender}")
            if not plan: return "Tell me your walk first, for example: Moscone Center to City Hall at 11:30 PM."
            w = await _post("/api/walks", {**plan, "walker": "Walker", "guardian": "Guardian", "choice": "hootroute"}, 60)
            base = public or ENGINE_URL
            return (f"Your walk has started. Open this on your phone to walk with me (keep it private, it lets you act as the walker): {base}{w['walkPath']}&t={w['walkerToken']}\n"
                    f"Send this to the person watching over you: {w['guardianUrl']}\n"
                    "If you stop on an empty stretch I'll check in; if you don't answer, my Rescuer alerts them step by step. HootRoute never calls 911.")
        pending = ctx.storage.get(f"approval:{sender}")
        try:
            if pending and sid and re.match(r"^(approve|approved|yes|ok|okay|go ahead|run it|check)\b", low):
                ctx.storage.set(f"approval:{sender}", None)
                res = await _post("/api/head/approve", {"session": sid, "approvalId": pending, "approve": True})
            elif pending and sid and re.match(r"^(skip|no|not now|don'?t)\b", low):
                ctx.storage.set(f"approval:{sender}", None)
                res = await _post("/api/head/approve", {"session": sid, "approvalId": pending, "approve": False})
            else:
                res = await _post("/api/head/ask", {"text": text, "session": sid, "allowChecks": False})
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404: ctx.storage.set(f"approval:{sender}", None); return "That request expired. Tell me your walk again."
            if e.response.status_code == 429: return "Too many requests right now. Please wait a moment and try again."
            return f"The HootRoute planner answered {e.response.status_code}. Please try again in a moment."
        except httpx.HTTPError as e:
            return f"I couldn't reach the HootRoute planner right now ({type(e).__name__}). Please try again in a moment."
        ap = res.get("pendingApproval")
        if ap: ctx.storage.set(f"approval:{sender}", ap["id"])
        ctx.storage.set(f"session:{sender}", res["session"])
        if res.get("req") and res.get("planId"):
            q = res["req"]; ctx.storage.set(f"plan:{sender}", {"planId": res["planId"], "origin": q["origin"], "destination": q["destination"], "day": q["day"], "minute": q["minute"]})
        if ap and ap["provider"] != "unavailable":
            names = ", ".join(p["name"] for p in ap["places"])
            tail = f"\n\nI'd like Sherlock to check the published listings of {names} (up to ${ap['maxUsd']:.2f}). Reply **approve** or **skip**."
        else:
            tail = "\n\nSay **start my walk** when you're ready." if res.get("planId") else ""
        return res["answer"] + _trace(res) + tail

    @chat.on_message(ChatMessage)
    async def on_chat(ctx: Context, sender: str, msg: ChatMessage):
        await ctx.send(sender, ChatAcknowledgement(timestamp=_now(), acknowledged_msg_id=msg.msg_id))      # always ack first
        texts = [i.text for i in msg.content if isinstance(i, TextContent)]
        if not texts and any(isinstance(i, StartSessionContent) for i in msg.content): texts = ["help"]
        if not texts: return
        try: reply = await handle(ctx, sender, " ".join(texts).strip())
        except Exception as e:
            ctx.logger.exception("head failed"); reply = f"Sorry, something went wrong on my side ({type(e).__name__}). Please try again."
        await ctx.send(sender, _chat(reply))

    @chat.on_message(ChatAcknowledgement)
    async def on_ack(ctx: Context, sender: str, msg: ChatAcknowledgement):
        ctx.logger.debug(f"ack from {sender} for {msg.acknowledged_msg_id}")

    agent.include(chat, publish_manifest=(mode() != "local"))
    return agent


if __name__ == "__main__":
    a = build_head(); print(f"hootroute-head address: {a.address}"); a.run()
