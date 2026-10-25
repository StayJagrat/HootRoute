"""watcher: during an active walk, check in with the user (relayed through scout, the chat agent) and escalate to the rescuer if they stop replying.

Run alone:  python watcher.py
"""
from __future__ import annotations

import os
import time

from uagents import Context

from common import CORE, address_of, make_agent
from models import CheckInAck, RescueDone, RescueTrigger, UserNotice, WalkStart, WalkStop


def build_watcher():
    agent = make_agent(CORE["watcher"]["name"], CORE["watcher"]["seed_env"], CORE["watcher"]["port"], "watcher.md")
    walks: dict[str, dict] = {}                       # key: user address. In-memory by design: a restart ends active walks.
    tick = float(os.environ.get("WATCHER_TICK_S", "10"))

    @agent.on_message(WalkStart)
    async def on_start(ctx: Context, sender: str, msg: WalkStart):
        if sender != address_of("scout"): ctx.logger.warning("WalkStart from non-scout ignored"); return
        now = time.time()
        walks[msg.user] = dict(msg=msg, next_checkin=now + msg.check_every_s, pending_since=None, escalated=False, ends=now + msg.expected_minutes * 60 * 1.5 + 2 * msg.check_every_s)
        ctx.logger.info(f"walk started: {msg.label} for {msg.user[:14]}, check-in every {msg.check_every_s}s")

    @agent.on_message(WalkStop)
    async def on_stop(ctx: Context, sender: str, msg: WalkStop):
        if sender == address_of("scout") and walks.pop(msg.user, None): ctx.logger.info("walk stopped by user")

    @agent.on_message(CheckInAck)
    async def on_ack(ctx: Context, sender: str, msg: CheckInAck):
        w = walks.get(msg.user)
        if sender == address_of("scout") and w: w["pending_since"] = None; w["next_checkin"] = time.time() + w["msg"].check_every_s; ctx.logger.info("check-in acknowledged")

    @agent.on_message(RescueDone)
    async def on_rescue_done(ctx: Context, sender: str, msg: RescueDone):
        if sender != address_of("rescuer"): return
        await ctx.send(address_of("scout"), UserNotice(user=msg.user, text=msg.summary))

    @agent.on_interval(period=tick)
    async def tick_walks(ctx: Context):
        now = time.time()
        for user, w in list(walks.items()):
            m: WalkStart = w["msg"]
            if now > w["ends"]:
                await ctx.send(address_of("scout"), UserNotice(user=user, text="Your walk window has ended, so I stopped checking in. Say **start walk** again if you are still walking."))
                walks.pop(user, None); continue
            if w["pending_since"] is not None:
                late = now - w["pending_since"]
                if late > m.reply_deadline_s and not w["escalated"]:
                    w["escalated"] = True
                    ctx.logger.warning(f"no reply for {late:.0f}s: triggering rescuer")
                    await ctx.send(address_of("rescuer"), RescueTrigger(session=m.session, user=user, label=m.label, reason=f"No reply to check-in for {late:.0f}s",
                                                                      minutes_overdue=late / 60, route_coords=m.route_coords, destination=m.destination))
            elif now >= w["next_checkin"]:
                w["pending_since"] = now
                await ctx.send(address_of("scout"), UserNotice(user=user, text=f"Check-in: are you okay? Reply **ok** within {m.reply_deadline_s}s. If I hear nothing, my rescuer will prepare a handoff packet for your trusted contact (it never contacts emergency services)."))

    return agent


if __name__ == "__main__":
    a = build_watcher(); print(f"watcher address: {a.address}"); a.run()
