"""reporter: turns a user's complaint (broken street light etc.) into a DRAFT 311 report in a local text file.

It NEVER submits anything. The user reviews the draft and files it themselves (SF311).
Run alone:  python reporter.py
"""
from __future__ import annotations

from datetime import datetime, timezone

from uagents import Context

from common import CORE, OUT_DIR, address_of, make_agent, slug
from models import ReportDraft, ReportRequest


def classify(issue: str) -> str:
    t = issue.lower()
    if any(w in t for w in ("light", "lamp", "dark", "bulb")): return "Street and Sidewalk: Streetlight out / needs repair"
    if any(w in t for w in ("graffiti", "tag")): return "Graffiti"
    if any(w in t for w in ("trash", "garbage", "litter", "dump")): return "Street and Sidewalk Cleaning"
    if any(w in t for w in ("pothole", "sidewalk", "crack", "broken")): return "Street and Sidewalk Defects"
    return "Other (describe below)"


def build_reporter():
    agent = make_agent(CORE["reporter"]["name"], CORE["reporter"]["seed_env"], CORE["reporter"]["port"], "reporter.md")

    @agent.on_message(ReportRequest, replies=ReportDraft)
    async def on_request(ctx: Context, sender: str, msg: ReportRequest):
        if sender != address_of("scout"): ctx.logger.warning("ReportRequest from non-scout ignored"); return
        ts = datetime.now(timezone.utc); loc = f"{msg.place_label}" + (f" (approx. {msg.lat:.5f}, {msg.lon:.5f})" if msg.lat is not None and msg.lon is not None else "")
        text = "\n".join(["DRAFT - NOT SUBMITTED - review and file it yourself at sf311.org or by calling 311", "",
                          f"Category: {classify(msg.issue)}", f"Location: {loc}", f"Reported by: Streetwise walker (drafted {ts.strftime('%Y-%m-%d %H:%M')} UTC)",
                          "Description:", f"  While walking at night I noticed: {msg.issue}. The location is hard to see after dark and walkers rely on this stretch.",
                          *( ["Notes: " + msg.notes] if msg.notes else [] ), "", "Attach a photo if you can."])
        OUT_DIR.mkdir(parents=True, exist_ok=True); d = OUT_DIR / "311_drafts"; d.mkdir(parents=True, exist_ok=True)
        path = d / f"311_draft_{ts.strftime('%Y%m%dT%H%M%S')}_{slug(msg.issue)[:24]}.txt"; path.write_text(text + "\n")
        ctx.logger.info(f"draft 311 report written: {path} (not submitted)")
        await ctx.send(sender, ReportDraft(session=msg.session, path=str(path), text=text, submitted=False))

    return agent


if __name__ == "__main__":
    a = build_reporter(); print(f"reporter address: {a.address}"); a.run()
