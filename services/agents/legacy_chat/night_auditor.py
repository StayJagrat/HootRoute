"""night_auditor: periodically asks the engine's auditor how complete its data is (places with no listed hours, lamp evidence, open outages).

Run alone:  python night_auditor.py
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from uagents import Context

from common import CORE, OUT_DIR, Engine, address_of, make_agent
from models import AuditReport, AuditRequest


def build_night_auditor():
    agent = make_agent(CORE["night_auditor"]["name"], CORE["night_auditor"]["seed_env"], CORE["night_auditor"]["port"], "night_auditor.md")
    engine = Engine(); every = float(os.environ.get("AUDIT_EVERY_S", "3600"))

    async def run_audit(session: str) -> AuditReport:
        try: res = await engine.audit(session)
        except Exception as e: return AuditReport(ok=False, summary=f"Audit failed: the engine did not answer ({type(e).__name__}).")
        OUT_DIR.mkdir(parents=True, exist_ok=True); path = OUT_DIR / "audit_latest.json"
        path.write_text(json.dumps(dict(at=datetime.now(timezone.utc).isoformat(), **res), indent=2))
        top = ", ".join(f"{k} ({v})" for k, v in res.get("top_missing", [])) or "none"
        return AuditReport(ok=True, path=str(path), summary=f"Night audit: {res['no_hours']} of {res['places']} places in the area have no listed hours and count as closed (most missing: {top}). "
                           f"{res['lamp_evidence']} lamp locations inferred from past 311 reports; {res['open_outages']} open outage reports are subtracted from lighting.")

    @agent.on_event("startup")
    async def first(ctx: Context): ctx.logger.info((await run_audit("auditor")).summary)

    @agent.on_interval(period=every)
    async def periodic(ctx: Context): ctx.logger.info((await run_audit("auditor")).summary)

    @agent.on_message(AuditRequest, replies=AuditReport)
    async def on_request(ctx: Context, sender: str, msg: AuditRequest):
        if sender != address_of("scout"): ctx.logger.warning("AuditRequest from non-scout ignored"); return
        await ctx.send(sender, await run_audit(msg.session))

    return agent


if __name__ == "__main__":
    a = build_night_auditor(); print(f"night_auditor address: {a.address}"); a.run()
