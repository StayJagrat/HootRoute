# HootRoute handoff

Deadline: **Sunday Oct 25, 2026, 9:00 AM PT** (be at the venue by 8:00 AM). Submission kit: `docs/SUBMISSION.md`.

## State (Oct 24, night)
| Part | Where | State |
|---|---|---|
| PWA | `web/` | Welcome walkthrough, plan (Head ask, routes, Checker verdict, live check), walk (voice, check-in, ladder, Call 911, report), guardian, shop, control room. Owl brand. Builds clean |
| Gateway | `services/api/hootroute_api/` | REST + one WebSocket room per walk, role-checked messages, walker tokens, SQLite, Head and Checker endpoints, abandoned walks expire |
| Agents | `services/agents/hootroute_agents/` | Head (`head_brain.py`, Claude tool use + walk report + audit), Guide, Checker (`inspect_route.py`, `hours_check.py`), Rescuer (ladder). In-process or as uAgents (`live_bureau.py`) |
| ASI:One | `services/agents/head_chat.py` | Chat Protocol front door; plan → check hours → start walk tested locally. Needs seeds + Agentverse mailbox |
| Engine | `services/engine/hootroute_engine/` | Citywide SF, deterministic score, regional calibration |
| Data | `data/cache/` | OSM, SF 311, BART, hours evidence. Closures: run `scripts/fetch_closures.py` (SFMTA 8x25-yybr) on a networked machine |
| Tests | `services/api/tests/` | 6 end-to-end tests, all passing |

Stage route: Moscone Center → City Hall, Fri 11:30 PM: HootRoute 77 vs fastest 57, longest empty stretch 390 m vs 560 m, +1.1 min.

## Before the demo
1. `.env`: `ANTHROPIC_API_KEY`, `APIFY_TOKEN`, `TWILIO_*`, `CARTESIA_API_KEY` (each optional).
2. `.venv/bin/python scripts/fetch_closures.py` and `./scripts/fetch_tiles.sh` (offline basemap).
3. Run one live listing check on the stage route; screenshot the Apify run.
4. Agentverse: seeds, `head_chat.py`, Connect → Mailbox, addresses into README.
5. Use replay ×10 in `/setup` for the stage walk.

## Log
- 2026-10-24: backend imported, gateway, citywide routing, planner (Codex + Claude).
- 2026-10-24 evening: relay gateway, agents drive real walks, uAgents bureau, Twilio, Cartesia proxy.
- 2026-10-24 night: rebuilt as **HootRoute** with four agents (Head, Guide, Checker, Rescuer), Claude orchestration, live Apify hours check, Checker route inspection with SFMTA closures, rescue ladder, owl brand and mascot, welcome walkthrough and four-step flow. Old chat agents and the old frontend removed.
