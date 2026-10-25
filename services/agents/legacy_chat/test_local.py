"""Offline end-to-end test: NO Agentverse, NO ASI:One, NO internet. Needs only the Streetwise engine on ENGINE_URL (default http://localhost:8000).

    ../../.venv-agents/bin/python test_local.py

It runs scout + 3 simulated shop agents + watcher + rescuer + reporter + night_auditor in one local Bureau (STREETWISE_MODE=local,
throwaway test seeds), plus a client agent that talks to scout through the real Agent Chat Protocol exactly as ASI:One would.
"""
import asyncio
import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

os.environ.update(STREETWISE_MODE="local", STREETWISE_ALLOW_DEV_SEEDS="1", WATCH_CHECK_EVERY_S="3", WATCH_REPLY_DEADLINE_S="4", WATCHER_TICK_S="1",
                  AUDIT_EVERY_S="3600", SCOUT_CARDS="1", OUT_DIR=tempfile.mkdtemp(prefix="streetwise_out_"), BUREAU_PORT="8199", PLACE_ASK_TIMEOUT_S="8")
os.environ.pop("ASI1_API_KEY", None)         # prove the deterministic path works alone
os.environ.pop("SCOUT_FIXED_SESSION", None)

from uagents import Agent, Bureau, Context, Protocol                                                         # noqa: E402
from uagents_core.contrib.protocols.chat import (ChatAcknowledgement, ChatMessage, EndSessionContent, MetadataContent, TextContent, chat_protocol_spec)  # noqa: E402

from common import Engine, address_of, local_bureau_policy, seed_for                                                               # noqa: E402
from parser import SF, parse_request                                                                         # noqa: E402
from registry import build_all                                                                               # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name); print(("  PASS  " if cond else "  FAIL  ") + name + (f"   [{detail}]" if detail and not cond else "")); return cond


async def unit_tests():
    print("\n[1] parser + engine (no agents)")
    e = Engine()
    try: lm = await e.landmarks()
    except Exception as ex: print(f"ENGINE NOT REACHABLE at {e.base}: {ex}"); sys.exit(2)
    now = datetime(2026, 10, 23, 15, 0, tzinfo=SF)
    p = parse_request("Walk me from Powell BART to Civic Center at 11:40pm Friday", lm, now=now)
    check("parse origin/dest/time", p.ok and p.origin.name == "Powell St BART" and p.dest.name == "Civic Center BART" and (p.day, p.minute) == (4, 1420), str(p))
    p = parse_request("take me to the Ferry Building from Montgomery at 1am saturday", lm, now=now)
    check("parse reversed order + after-midnight", p.ok and p.origin.name.startswith("Montgomery") and p.dest.name == "Ferry Building" and (p.day, p.minute) == (4, 1500), str(p))
    p = parse_request("hello there", lm, now=now); check("non-route text is rejected politely", not p.ok and p.errors)
    p = parse_request("from powell to atlantis at 9pm", lm, now=now); check("unknown place gives suggestions", not p.ok and "Places I know" in p.errors[0])
    out = await e.route("t-unit", (37.7844, -122.4079), (37.7796, -122.4139), 4, 1420)
    check("engine /api/route returns fast and best", {r["id"] for r in out["routes"]} == {"fast", "best"}); await e.reset("t-unit")


async def e2e():
    print("\n[2] full flow through the Agent Chat Protocol (local Bureau)")
    inbox: asyncio.Queue = asyncio.Queue(); done = asyncio.Event(); results = {}
    client = Agent(name="test-client", seed=seed_for("TEST_CLIENT_SEED"), port=8190, endpoint=["http://127.0.0.1:8190/submit"], enable_agent_inspector=False)
    chat = Protocol(spec=chat_protocol_spec); scout = address_of("scout")

    @chat.on_message(ChatMessage)
    async def got(ctx: Context, sender: str, msg: ChatMessage):
        await ctx.send(sender, ChatAcknowledgement(timestamp=datetime.now(timezone.utc), acknowledged_msg_id=msg.msg_id))
        await inbox.put(msg)

    @chat.on_message(ChatAcknowledgement)
    async def ack(ctx: Context, sender: str, msg: ChatAcknowledgement): results["acks"] = results.get("acks", 0) + 1

    client.include(chat)

    async def say(ctx, text, wait=60):
        await ctx.send(scout, ChatMessage(timestamp=datetime.now(timezone.utc), msg_id=__import__("uuid").uuid4(), content=[TextContent(type="text", text=text)]))
        return await asyncio.wait_for(inbox.get(), wait)

    def txt(m): return "".join(c.text for c in m.content if isinstance(c, TextContent))

    @client.on_event("startup")
    async def script(ctx: Context):
        try:
            await asyncio.sleep(3)
            m = await say(ctx, "hi"); results["help"] = txt(m)
            t0 = time.time(); m = await say(ctx, "Walk me from Powell BART to Civic Center at 11:40pm Friday"); results["plan"] = txt(m); results["plan_msg"] = m; results["plan_s"] = time.time() - t0
            os.environ["SCOUT_CARDS"] = "0"            # same process: flip scout to text-only and check the plain path too
            m = await say(ctx, "Walk me from Union Square to Ferry Building at 10pm Friday"); results["plain_msg"] = m; results["plain"] = txt(m)
            m = await say(ctx, "Walk me from Powell BART to Civic Center at 11:40pm Friday"); results["plan_msg"] = results["plan_msg"]
            m = await say(ctx, "start walk"); results["start"] = txt(m)
            m = await asyncio.wait_for(inbox.get(), 20); results["checkin1"] = txt(m)
            m = await say(ctx, "ok"); results["ok"] = txt(m)
            m = await asyncio.wait_for(inbox.get(), 20); results["checkin2"] = txt(m)         # second check-in: we stay silent
            m = await asyncio.wait_for(inbox.get(), 20); results["rescue"] = txt(m)
            m = await say(ctx, "stop walk"); results["stop"] = txt(m)
            m = await say(ctx, "report broken light near Civic Center BART"); results["report"] = txt(m)
            m = await say(ctx, "audit"); results["audit"] = txt(m)
            m = await say(ctx, "asdf qwer"); results["junk"] = txt(m)
        except Exception as ex:
            results["error"] = repr(ex)
        finally:
            done.set()

    bureau = Bureau(port=int(os.environ["BUREAU_PORT"]), endpoint=[f"http://127.0.0.1:{os.environ['BUREAU_PORT']}/submit"], registration_policy=local_bureau_policy())
    for a in build_all(): bureau.add(a)
    bureau.add(client)
    task = asyncio.create_task(bureau.run_async())
    try: await asyncio.wait_for(done.wait(), 150)
    except asyncio.TimeoutError: results["error"] = "overall timeout"
    # no graceful Bureau shutdown: the process exits right after reporting (see main)

    print("\n----- scout reply to the route request -----\n" + results.get("plan", "<none>") + "\n---------------------------------------------")
    check("no script error", "error" not in results, results.get("error", ""))
    check("scout acknowledged our message (chat protocol ack)", results.get("acks", 0) >= 1)
    check("help text for greeting", "Streetwise Scout" in results.get("help", ""))
    plan = results.get("plan", "")
    check("reply has fast vs Streetwise table with scores", "| Score" in plan and "Fastest" in plan and "Streetwise" in plan)
    check("reply names the longest empty stretch", "Longest empty stretch" in plan)
    check("a shop agent confirmed and score change is reported", "Shop agent confirmed" in plan and "to" in plan.split("Shop agent confirmed")[-1] and "simulated demo shop agent" in plan, plan[-400:])
    check("interactive card attached when SCOUT_CARDS=1 (text still present, session left open for the card)", any(isinstance(c, MetadataContent) for c in results["plan_msg"].content) and any(isinstance(c, TextContent) for c in results["plan_msg"].content))
    check("text-only reply (cards off) has no card and ends the session", "plain_msg" in results and not any(isinstance(c, MetadataContent) for c in results["plain_msg"].content) and any(isinstance(c, EndSessionContent) for c in results["plain_msg"].content))
    check("a different route also answers (Union Square -> Ferry Building)", "Union Square to Ferry Building" in results.get("plain", "") and "| Score" in results.get("plain", ""), results.get("plain", "")[:200])
    check("walk started", "Walk started" in results.get("start", ""))
    check("watcher check-in relayed to the user", "Check-in" in results.get("checkin1", ""))
    check("user 'ok' acknowledged", "checked in" in results.get("ok", ""))
    check("silence triggers rescuer handoff packet notice", "handoff packet" in results.get("rescue", "") and "NOT contacted emergency services" in results.get("rescue", "").replace("have NOT", "NOT"), results.get("rescue", ""))
    packets = list(Path(os.environ["OUT_DIR"], "handoffs").glob("*.json")); check("handoff packet file written, emergency_services_contacted=false", bool(packets) and '"emergency_services_contacted": false' in packets[0].read_text())
    check("walk stop", "Walk ended" in results.get("stop", ""))
    drafts = list(Path(os.environ["OUT_DIR"], "311_drafts").glob("*.txt")); check("311 report drafted to file and marked DRAFT/not submitted", bool(drafts) and "DRAFT - NOT SUBMITTED" in drafts[0].read_text() and "nothing has been submitted" in results.get("report", ""))
    check("night auditor answered", "Night audit" in results.get("audit", ""), results.get("audit", ""))
    check("junk input yields help, not a crash", "Streetwise Scout" in results.get("junk", ""))
    print(f"\n  route request took {results.get('plan_s', 0):.1f}s end-to-end")
    print("\n----- rescue notice -----\n" + results.get("rescue", "") + "\n----- 311 draft -----\n" + (drafts[0].read_text() if drafts else ""))


async def main():
    await unit_tests(); await e2e()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed" + (": " + "; ".join(FAIL) if FAIL else "")); sys.stdout.flush(); os._exit(1 if FAIL else 0)

asyncio.run(main())
