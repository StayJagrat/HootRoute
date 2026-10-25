"""hootroute-head: the HootRoute Head on Agentverse, usable entirely inside an ASI:One chat (Agent Chat Protocol).

The whole primary workflow runs in the conversation: the walker describes the walk, the Head (Claude) has the Guide plan and
score both routes and the Checker look for places with unknown hours; "check the hours" runs a live Apify listing check and
re-scores, in the same chat. "Start my walk" creates a real walk and returns the walker and guardian links.

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

HELP = ("Hi, I'm the Head of HootRoute, a walking companion for San Francisco late-shift workers.\n\n"
        "Tell me your walk, for example: **My shift ends at 11:30 PM near Moscone Center, walk me to City Hall, I'd like more places open.**\n"
        "I'll have my Guide score the fastest route and a better-lit, more-open one, and my Checker look for places whose hours are unknown. "
        "Then you can say **check the hours** (a live listing check) or **start my walk** (you get a walker link and a link for the person watching over you).\n\n"
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
    lines = [f"- **{t['agent'].capitalize()}** · {t['tool'].replace('_', ' ')} · {t['summary']}" for t in res.get("trace", [])]
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
        try:
            res = await _post("/api/head/ask", {"text": text, "session": sid, "allowChecks": True})
        except httpx.HTTPError as e:
            return f"I couldn't reach the HootRoute planner right now ({type(e).__name__}). Please try again in a moment."
        ctx.storage.set(f"session:{sender}", res["session"])
        if res.get("req") and res.get("planId"):
            q = res["req"]; ctx.storage.set(f"plan:{sender}", {"planId": res["planId"], "origin": q["origin"], "destination": q["destination"], "day": q["day"], "minute": q["minute"]})
        tail = "\n\nSay **check the hours** to verify listings live, or **start my walk**." if res.get("planId") and not res.get("check") else "\n\nSay **start my walk** when you're ready." if res.get("planId") else ""
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
