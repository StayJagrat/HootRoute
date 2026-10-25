"""The four HootRoute agents: Head, Guide, Checker and Rescuer.

Head (Claude) interprets the request, delegates, writes the walk report and runs the overnight audit. Guide plans and re-plans
with the deterministic engine. Checker inspects the route before you leave and follows the walk. Rescuer runs the escalation
ladder: live link, SMS, call, backup contact, and a Call 911 button for people (it never dials 911 itself).

Each agent reacts to room envelopes and to messages from the other agents (`tell`), and answers with the message types in
web/src/lib/types.ts. Every automatic action is spoken or logged with a reason. Scores come from the engine only.
No agent calls 911 and no report is ever submitted to the city.
"""
from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from hootroute_engine import geo

from .brand import BRAND
from .head_brain import write_report
from .walk import Walk

if TYPE_CHECKING:
    from .runtime import Runtime

log = logging.getLogger("hootroute.agents")

TURN_AHEAD_M = 130
PLACE_AHEAD_M = 70
DIM_AHEAD_M = 60
MOVE_M = 15            # a fix this far from the last anchor counts as moving
ARRIVE_M = 25
OFF_ROUTE_M = 40
OFF_ROUTE_FIXES = 3
REPLAN_EVERY_S = 45
GPS_QUIET_S = 60


def clock(minute: float) -> str:
    m = int(round(minute)) % 1440; h, mm = divmod(m, 60)
    return f"{(h % 12) or 12}:{mm:02d} {'AM' if h < 12 else 'PM'}"


def hhmm(text: str) -> str:
    """'01:00' -> '1 AM', '23:30' -> '11:30 PM'."""
    try: h, m = map(int, text.split(":"))
    except ValueError: return text
    if h == 0 and m == 0: return "midnight"
    return f"{(h % 12) or 12}{f':{m:02d}' if m else ''} {'PM' if h >= 12 else 'AM'}"


def secs(w: Walk, v: float) -> str:
    """A threshold in walker time: a replay runs ×time_scale faster, so say the real-world seconds and label the replay."""
    return f"{v * w.time_scale:g} s (×{w.time_scale:g} replay)" if w.replay and w.time_scale > 1 else f"{v:g} s"


def wall_clock(ts: float) -> str:
    return time.strftime("%-I:%M %p", time.localtime(ts))


class Agent:
    name = "agent"

    def __init__(self, rt: "Runtime"):
        self.rt = rt; self.eng = rt.engine

    async def log(self, w: Walk, text: str, reason: str, to: str | None = None):
        msg = {"type": "agent.log", "agent": self.name, "text": text, "reason": reason}
        if to: msg["to"] = to
        await self.rt.send(w, msg)

    async def say(self, w: Walk, text: str):
        await self.rt.send(w, {"type": "voice.say", "agent": self.name, "text": text})


# ------------------------------------------------------------------------------------------------------------- Guide
class Guide(Agent):
    """Guide: plans the route by what is lit and open at the minute you pass each block, explains it, re-plans when you leave it."""
    name = "guide"

    def plan_msg(self, w: Walk, reason: str) -> dict:
        return {"type": "walk.plan", "plan": {"routeId": w.id, "stats": w.data["stats"], "reason": reason, "thresholds": w.thresholds,
                                              "guardian": w.guardian, "walker": w.walker, "replay": w.replay, "timeScale": w.time_scale, "data": w.data}}

    @staticmethod
    def explain(stats: dict) -> str:
        s, f = stats["hootroute"], stats["shortest"]
        if s == f or (s["score"] == f["score"] and s["minutes"] == f["minutes"]):
            return f"The shortest route is already the best I found at this hour: score {f['score']}, longest stretch without a listed open place or help point {f['longestEmptyM']} m. Conditions, not a safety rating."
        return (f"The HootRoute route scores {s['score']} versus {f['score']} for the shortest, for {s['minutes'] - f['minutes']:+.1f} min. "
                f"Its longest stretch without a listed open place or help point is {s['longestEmptyM']} m versus {f['longestEmptyM']} m. Conditions, not a safety rating.")

    async def request(self, w: Walk, cached: tuple[dict, dict] | None = None):
        await self.log(w, f"Planning {w.origin.get('name', 'Start')} → {w.dest.get('name', 'Destination')}, {self.eng.day_name(w.day)} {clock(w.minute)}.",
                       f"{w.walker} asked for a walk. Scoring every candidate route at the minute each block is passed.")
        try:
            data, routes = cached or await self.eng.plan(w.origin, w.dest, w.day, w.minute, w.walker, w.guardian)
        except ValueError as e:
            await self.log(w, f"Could not plan this walk: {e}", "The start or destination is outside the mapped part of San Francisco.")
            await self.rt.send(w, {"type": "walk.end", "outcome": "ended", "summary": f"Guide could not plan this walk: {e}"}); w.status = "ended"; return
        w.set_plan(data, routes); w.status = "planned"
        opened = [p for p in data["places"] if p["openUntil"] != "closed"]
        await self.log(w, f"{len(routes['best']['shops'])} places listed open along the HootRoute route at the time you pass them.",
                       "OSM opening hours plus matched hours evidence; places with no listed hours count as closed.", "Checker")
        await self.rt.send(w, self.plan_msg(w, self.explain(data["stats"])))
        await self.say(w, f"The HootRoute route scores {data['stats']['hootroute']['score']} versus {data['stats']['shortest']['score']} for the shortest route. "
                          + (f"{opened[0]['name']} is open along the way. " if opened else "") + "I'm ready when you are.")

    async def accept(self, w: Walk, choice: str):
        if not w.data: return
        w.set_choice(choice)
        label = "shortest route" if w.choice == "usual" else "HootRoute route"
        await self.log(w, f"WalkPlan sent to Checker: {label}, score {w.data['stats']['shortest' if w.choice == 'usual' else 'hootroute']['score']}.",
                       f"{w.walker} chose the {label}.", "Checker")

    async def first_instruction(self, w: Walk):
        steps = [s for s in w.steps() if s["street"] != "the path"]
        turn = next((s for s in w.steps()[1:] if "left" in s["maneuver"] or "right" in s["maneuver"]), None)
        head = steps[0]["street"] if steps else "the walking path"
        await self.say(w, f"Okay, I'm walking with you. Head along {head}" + (f", then {turn['maneuver']} on {turn['street']}." if turn else "."))

    async def turns(self, w: Walk):
        for s in w.steps()[1:]:
            if not ("left" in s["maneuver"] or "right" in s["maneuver"]): continue
            key = f"turn:{s['at_m']}"
            if key in w.said: continue
            ahead = s["at_m"] - w.meters
            if 0 < ahead <= TURN_AHEAD_M:
                w.said.add(key); street = "the walking path" if s["street"] == "the path" else s["street"]
                await self.say(w, f"{s['maneuver'].capitalize()} on {street} in about {max(10, round(ahead / 10) * 10)} metres."); return True
        return False

    async def replan(self, w: Walk, at: list[float]):
        w.last_replan = time.time(); w.offroute = 0
        where = await self.eng.where(at)
        await self.log(w, f"Re-planning from {where} to {w.dest.get('name')}.", f"{w.walker} has been more than {OFF_ROUTE_M} m from the route for {OFF_ROUTE_FIXES} fixes.", "Checker")
        elapsed = (time.time() - (w.started or time.time())) / 60 * (w.time_scale if w.replay else 1)
        try:
            data, routes = await self.eng.plan({"lat": at[1], "lon": at[0], "name": where}, w.dest, w.day, int(w.minute + elapsed) % 1440, w.walker, w.guardian)
        except ValueError as e:
            await self.log(w, f"Re-plan failed: {e}", "Staying on the original route."); return
        w.set_plan(data, routes); w.set_choice("hootroute"); w.meters = 0.0; w.said = {k for k in w.said if not k.startswith(("turn:", "place:", "dim:"))}
        await self.rt.send(w, self.plan_msg(w, f"Rerouted from {where}. " + self.explain(data["stats"])))
        await self.say(w, f"You're off the planned route. I found a new way from here, about {round(data['stats']['hootroute']['minutes'])} minutes.")

    async def place_update(self, w: Walk, place_id: str, decl: dict):
        """A shopkeeper changed their hours. Before the walk: plan again. During it: re-score the fixed routes and tell the walker if it is ahead."""
        info = self.eng.place(place_id); name = (info or {}).get("name") or "A place"
        open_ = decl["openUntil"] != "closed"
        desc = f"staying open until {hhmm(decl['openUntil'])}" if open_ and decl["openUntil"] != "24h" else "open all night" if open_ else "closed for the night"
        await self.log(w, f"Place update · {name}: {desc}" + (", front light on" if decl.get("frontLight") else "") + ".", "Shopkeeper declaration on the shop page.", "Guide")
        if not w.data: return
        if w.status in ("planning", "planned"):
            before = w.data["stats"]
            try: data, routes = await self.eng.plan(w.origin, w.dest, w.day, w.minute, w.walker, w.guardian)
            except ValueError: return
            w.set_plan(data, routes)
            self._merge_place(w, place_id, info, decl)
            await self.rt.send(w, self.plan_msg(w, f"{name} updated its hours. " + self.explain(data["stats"])))
            await self.log(w, f"Re-planned after {name}'s update: {before['hootroute']['score']} → {data['stats']['hootroute']['score']} (HootRoute), "
                              f"{before['shortest']['score']} → {data['stats']['shortest']['score']} (shortest).", "Listed hours change open places and empty stretches.")
            return
        stats = await self.eng.rescore(w.routes, w.day, w.minute)
        before = w.data["stats"]; w.data = {**w.data, "stats": stats}
        self._merge_place(w, place_id, info, decl)
        await self.rt.send(w, self.plan_msg(w, f"{name} updated its hours. The fixed routes now score {stats['hootroute']['score']} versus {stats['shortest']['score']}. Conditions, not a safety rating."))
        await self.log(w, f"Re-scored the fixed routes: {before['hootroute']['score']} → {stats['hootroute']['score']} (HootRoute), {before['shortest']['score']} → {stats['shortest']['score']} (shortest).",
                       "Listed hours affect open places and empty stretches. Front light is shown to walkers but is not a score input.", "Checker")
        if info and w.active:
            ahead, off = geo.project(w.line(), info["ll"], w.cum())
            if off <= 50 and ahead > w.meters: await self.say(w, f"{name} just told us it's {desc}. It's ahead on your route.")

    @staticmethod
    def _merge_place(w: Walk, place_id: str, info: dict | None, decl: dict):
        places = [dict(p) for p in w.data["places"]]; hit = next((p for p in places if p["id"] == place_id), None)
        fields = {"openUntil": decl["openUntil"], "safeHaven": bool(decl.get("safeHaven")), "frontLight": bool(decl.get("frontLight")), "simulated": False, "hoursSource": "shopkeeper"}
        if hit: hit.update(fields)
        elif info and info.get("name"):
            ahead, off = geo.project(w.line(), info["ll"], w.cum())
            if off <= 80: places.append({"id": place_id, "name": info["name"], "kind": "pharmacy" if info["cat"] == "pharmacy" else "market" if info["cat"] in ("convenience", "supermarket") else "cafe",
                                         "lngLat": info["ll"], "address": None, **fields})
        w.data = {**w.data, "places": places}


# ------------------------------------------------------------------------------------------------------------- Checker
class Checker(Agent):
    """Checker: inspects the route before you leave (see hours_check.py) and follows live positions: narrates what's ahead, notices stops on stretches with nothing open, checks in, hands silence to the Rescuer."""
    name = "checker"

    async def start(self, w: Walk):
        if not w.data: return
        w.status = "walking"; w.started = time.time(); w.moved_ts = time.time(); w.anchor = None; w.asked_here = False; w.said = set()
        t = w.thresholds
        await self.log(w, f"Following live positions{' (GPS replay ×' + format(w.time_scale, 'g') + ')' if w.replay else ''}. Check in after {secs(w, t['stopSeconds'])} still on a stretch with nothing open; reply window {secs(w, t['replySeconds'])}.",
                       "Standing orders from the walker's setup.")
        await self.rt.agents["guide"].first_instruction(w)

    async def position(self, w: Walk, msg: dict):
        if not w.active or not w.data: return
        acc = msg.get("accuracy")
        if isinstance(acc, (int, float)) and acc > 60: return          # too coarse to judge a stop or a detour
        p = msg["lngLat"]; now = time.time()
        w.fix, w.fix_ts, w.gps_quiet_logged = p, now, False
        w.meters, w.offset = geo.project(w.line(), p, w.cum())
        move = max(MOVE_M, (acc or 0) * 0.6)
        if w.anchor is None or geo.distance(w.anchor, p) > move:
            w.anchor, w.moved_ts, w.asked_here = p, now, False
        if geo.distance(p, w.line()[-1]) <= ARRIVE_M or (w.total() - w.meters <= 20 and w.offset <= OFF_ROUTE_M):
            await self.rt.tell(self.name, "head", w, "arrived"); return
        w.offroute = w.offroute + 1 if w.offset > OFF_ROUTE_M else 0
        if w.offroute >= OFF_ROUTE_FIXES and now - w.last_replan > REPLAN_EVERY_S and not w.replay:
            await self.rt.tell(self.name, "guide", w, "replan", at=p); return
        if w.status == "walking": await self.narrate(w)

    async def narrate(self, w: Walk):
        if await self.rt.agents["guide"].turns(w): return
        for s in w.route()["shops"]:
            key = f"place:{s['id']}"
            if key in w.said: continue
            ahead, off = geo.project(w.line(), s["ll"], w.cum())
            if off < 45 and 0 < ahead - w.meters < PLACE_AHEAD_M:
                w.said.add(key); name = s["name"] or s["cat"].replace("_", " ")
                await self.say(w, f"{name} is just ahead, listed open."); return
        for d in w.data["dimStretches"]:
            key = f"dim:{d['id']}"
            if key in w.said or not d["line"]: continue
            start, off = geo.project(w.line(), d["line"][0], w.cum())
            if off < 25 and -10 < start - w.meters < DIM_AHEAD_M:
                w.said.add(key)
                await self.say(w, f"The next {d['meters']} metres have no listed open place. I'm with you."); return

    async def tick(self, w: Walk, now: float):
        t = w.thresholds
        if w.status == "walking":
            if w.fix_ts and now - w.fix_ts > GPS_QUIET_S and not w.gps_quiet_logged:
                w.gps_quiet_logged = True
                await self.log(w, f"No GPS fix for {GPS_QUIET_S} s. Treating the walker as still.", "The phone stopped reporting location; the stop timer keeps running.")
            if not w.asked_here and now - w.moved_ts >= t["stopSeconds"]:
                w.asked_here = True
                decision = await self.eng.decide(w.route(), w.meters)
                if decision["decision"] == "quiet":
                    await self.log(w, decision["msg"], decision["why"]); return
                w.status = "checkin"; w.checkins += 1; w.reply_deadline = now + t["replySeconds"]
                where = await self.eng.where(w.fix or w.line()[0])
                reason = f"Still for {secs(w, t['stopSeconds'])} on {where}, with no listed open place within 60 m."
                await self.rt.send(w, {"type": "checkin.ask", "agent": "checker", "text": "You stopped. All good?", "reason": reason,
                                       "windowSec": t["replySeconds"], "deadline": round(w.reply_deadline * 1000)})
                await self.say(w, "You stopped. All good?")
                await self.log(w, 'Asked aloud: "You stopped. All good?"', reason, w.walker)
        elif w.status == "checkin" and now >= w.reply_deadline:
            await self.rt.tell(self.name, "rescuer", w, "no_reply", reason=f"No reply for {secs(w, t['replySeconds'])}")

    async def reply(self, w: Walk, reply: str, via: str):
        if reply == "help":
            await self.rt.tell(self.name, "rescuer", w, "help"); return
        if w.status == "checkin":
            w.status = "walking"; w.moved_ts = time.time(); w.asked_here = True      # don't ask again until they move on
            await self.say(w, "Okay. Walking with you.")
            await self.log(w, f"Check-in cleared ({'said' if via == 'voice' else 'tapped'} I'm fine). Resuming.", "Walker answered.")
        elif w.status == "escalated":
            await self.rt.tell(self.name, "rescuer", w, "fine", via=via)


# ------------------------------------------------------------------------------------------------------------- Rescuer
LADDER = ["Live link + SMS to guardian", "Call guardian", "Text and call backup contact", "Call 911 button for people (never automatic)"]


class Rescuer(Agent):
    """Silence or Help starts the ladder: live link and SMS to the guardian, then a phone call, then the backup contact.

    Every rung waits `escalateSeconds` for someone to answer. The last rung is a Call 911 button shown to the walker and the
    guardian. HootRoute never dials 911 itself: an automatic call can't confirm an emergency and false alarms cost responders."""
    name = "rescuer"

    async def rung(self, w: Walk, step: int, status: str):
        await self.rt.send(w, {"type": "rescue.ladder", "step": step, "label": LADDER[step], "status": status, "steps": LADDER})

    async def escalate(self, w: Walk, reason: str):
        if w.status == "escalated" or not w.data: return
        w.status = "escalated"; w.escalated_reason = reason; w.acked_by = None; w.followed_up = False; w.ladder = 0
        w.escalate_deadline = time.time() + w.thresholds["escalateSeconds"]
        at = w.fix or w.line()[0]; where = await self.eng.where(at); w.last_where = where
        await self.rt.send(w, {"type": "escalate", "reason": reason, "lngLat": at})
        await self.rt.send(w, {"type": "guardian.alert", "reason": reason, "lngLat": at, "where": where})
        sms = await self.rt.notifier.sms(w.guardian_phone, f"{BRAND}: {w.walker} isn't answering ({reason.lower()}). Last seen on {where} at {wall_clock(time.time())}. "
                                                            f"Live map: {w.guardian_url} . {BRAND} does not call 911; if you think {w.walker} needs emergency help, call 911 yourself.")
        w.sms_sent = sms == "sent"
        await self.rung(w, 0, f"live link sent; SMS {sms}")
        await self.log(w, f"Step 1: alert on {w.first_name(w.guardian)}'s live link. SMS: {sms}. 911 not contacted.",
                       "Standing order: trusted contact first. This service never calls emergency services.", "Guardian")
        await self.log(w, f"Handoff packet ready · position {at[1]:.5f}, {at[0]:.5f} · {where} · {w.origin.get('name')} → {w.dest.get('name')} · {wall_clock(time.time())} · {reason}.",
                       "Everything a guardian or a dispatcher needs in one place.")
        await self.say(w, f"I've sent {w.first_name(w.guardian)} your live location. Say \"I'm fine\" or tap the button if you're okay.")

    async def fine(self, w: Walk, via: str):
        if w.status != "escalated": return
        w.status = "walking"; w.moved_ts = time.time(); w.asked_here = True
        await self.say(w, "Okay. I've told your guardian you're fine. Walking with you.")
        sms = await self.rt.notifier.sms(w.guardian_phone, f"{BRAND} update: {w.walker} says they're fine and is walking again.") if w.sms_sent else "not needed"
        await self.rung(w, w.ladder, "cleared: walker is fine")
        await self.log(w, f"Walker said they are fine. Guardian alert cleared. SMS update: {sms}.", "Check-in answered after escalation.", "Guardian")

    async def ack(self, w: Walk, by: str):
        if w.status != "escalated" or w.acked_by: return
        w.acked_by = by
        await self.say(w, f"{by} is on it.")
        await self.rung(w, w.ladder, f"cleared: {by} is on it")
        await self.log(w, f"{by} cleared the alert: \"I'm on it\". Ladder stopped.", "Guardian responded on the live link.", w.walker)

    async def tick(self, w: Walk, now: float):
        if w.status != "escalated" or w.acked_by or now < w.escalate_deadline or w.ladder >= len(LADDER) - 1: return
        w.ladder += 1; w.escalate_deadline = now + w.thresholds["escalateSeconds"]; wait = secs(w, w.thresholds['escalateSeconds'])
        where = getattr(w, "last_where", None) or "the last known position"
        if w.ladder == 1:
            call = await self.rt.notifier.call(w.guardian_phone, f"This is {BRAND}. {w.walker} is not answering check-ins. Last seen on {where}. "
                                                                  f"Open the live map link we texted you. {BRAND} does not call 911. If you think {w.walker} needs emergency help, call 911 yourself.")
            await self.rung(w, 1, f"call {call}")
            await self.log(w, f"Step 2: no answer after {wait}. Calling {w.first_name(w.guardian)}: {call}.", "Nobody cleared the alert, so the Rescuer moves one rung up.", "Guardian")
        elif w.ladder == 2:
            if w.backup_phone:
                sms = await self.rt.notifier.sms(w.backup_phone, f"{BRAND}: {w.walker} isn't answering and {w.first_name(w.guardian)} hasn't responded. Last seen on {where}. Live map: {w.guardian_url} . "
                                                                  f"{BRAND} does not call 911; call 911 yourself if you think it's an emergency.")
                call = await self.rt.notifier.call(w.backup_phone, f"This is {BRAND}. {w.walker} is not answering, and their first contact has not responded. Last seen on {where}. Check the link we texted you.")
                status = f"SMS {sms}, call {call}"
            else:
                status = "no backup contact set"
            await self.rung(w, 2, status)
            await self.log(w, f"Step 3: still no answer. Backup contact {w.backup_name or ''}: {status}.".replace("contact :", "contact:"), "Second trusted contact from the walker's setup.", "Backup")
        else:
            await self.rung(w, 3, "Call 911 button shown to walker and guardian")
            await self.log(w, "Step 4: nobody has answered. Showing a Call 911 button to the walker and the guardian. HootRoute does not dial 911 itself.",
                           "Only a person can confirm an emergency; an automatic call risks false alarms.")
            await self.say(w, "If you need emergency help, tap Call 911.")


# ------------------------------------------------------------------------------------------------------------- Head
class Head(Agent):
    """The Head: Claude interprets the request and delegates before the walk (head_brain.py), then closes every walk with a
    report and runs the overnight audit. Reports cite real open SF 311 case ids and are drafts: nothing is submitted."""
    name = "head"

    async def arrived(self, w: Walk):
        if w.status == "ended": return
        w.status = "ended"
        minutes = (time.time() - (w.started or time.time())) / 60 * (w.time_scale if w.replay else 1)
        cases = await self.eng.cases_near(w.line(), 40.0, 5)
        stats = w.data["stats"]["shortest" if w.choice == "usual" else "hootroute"]
        facts = {"walker": w.walker, "from": w.origin.get("name"), "to": w.dest.get("name"), "minutes": round(minutes), "route": "fastest" if w.choice == "usual" else "HootRoute",
                 "score": stats["score"], "longest_empty_m": stats["longestEmptyM"], "checkins": w.checkins, "alerts": 1 if w.escalated_reason else 0,
                 "alert_reason": w.escalated_reason or None, "rescue_rung_reached": w.ladder if w.escalated_reason else None, "acked_by": w.acked_by,
                 "open_311_streetlight_cases": [{"id": c["id"], "details": c["details"], "opened": c["opened"]} for c in cases[:3]], "replay": w.replay}
        draft = None
        if cases:
            draft = ("DRAFT — not submitted. Streetlight follow-up along " + f"{w.origin.get('name')} → {w.dest.get('name')}. Open SF 311 cases already on record: "
                     + "; ".join(f"#{c['id']} ({c['details']}, opened {c['opened']})" for c in cases[:3]) + ". Confirm on site before filing.")
        report, by = await write_report(facts)
        msg = {"type": "walk.end", "outcome": "arrived", "summary": report, "reportBy": by}
        if draft: msg["draft311"] = draft
        await self.rt.send(w, msg)
        await self.say(w, f"You've arrived at {w.dest.get('name')}, {w.walker}.")
        await self.log(w, f"Walk report written ({by}). " + (f"Draft 311 cites {len(cases)} real open case{'s' if len(cases) != 1 else ''}." if cases else "No open 311 streetlight case on the route."),
                       "Reports stay drafts for a person to review. Numbers in the report come from the engine and the walk log, not from the model.", w.walker)
        if w.sms_sent: await self.rt.notifier.sms(w.guardian_phone, f"{BRAND}: {w.walker} has arrived. Location sharing has stopped.")

    async def ended(self, w: Walk):
        if w.status == "ended": return
        w.status = "ended"
        await self.log(w, "Walk ended by the walker. Location sharing stopped.", "Walker ended the walk.")

    async def run(self, w: Walk | None, day: int = 4, minute: int = 23 * 60) -> dict:
        """Overnight audit: rank streets by modeled walker-minutes on lower-light segments and draft a 311 note citing real open case ids."""
        if w: await self.log(w, "Running the overnight audit.", "Requested from the control room.")
        debt = await self.eng.darkness_debt(w.day if w else day, w.minute if w else minute, w.line() if w and w.data else None, 5)
        ranking = [{"street": r["street"], "minutes": r["minutes"]} for r in debt["rows"]]
        if not ranking:
            result = {"type": "audit.result", "ranking": [], "draft311": "DRAFT — not submitted. No modeled street ranking is available."}
        else:
            top = ranking[0]; cases = await self.eng.cases_on_street(top["street"], 3)
            cited = ("Open SF 311 streetlight cases already on record: " + "; ".join(f"#{c['id']} ({c['details']}, opened {c['opened']})" for c in cases) + ". "
                     if cases else "No open SF 311 streetlight case is on record for this street. ")
            result = {"type": "audit.result", "ranking": ranking,
                      "draft311": f"DRAFT — not submitted. Streetlight review requested on {top['street']}. {cited}"
                                  f"Modeled walkers spend about {top['minutes']} minutes a night on its lower-light segments (modeled trips, not observed foot traffic). Confirm conditions before filing.",
                      "cases": cases}
        if w:
            await self.rt.send(w, result)
            if ranking: await self.log(w, f"Ranked modeled walker-minutes on lower-light streets. Top: {ranking[0]['street']} ({ranking[0]['minutes']} min). Draft 311 prepared.",
                                       "Modeled trips, not observed foot traffic. The draft cites only real case ids and is never submitted.")
        return result
