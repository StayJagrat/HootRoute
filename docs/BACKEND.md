# HootRoute backend

How the live app fits together: the gateway, the five agents, the engine, and the data they keep. For the message contract the PWA speaks, see `web/src/lib/types.ts`. For decisions and the plan, see [HANDOFF.md](HANDOFF.md).

## Shape

```
PWA (walker · guardian · shop · control room)
   │  REST  /api/plans  /api/walks  /api/places/{id}/declaration …
   │  WS    /ws?walk=<id>&role=<walker|guardian|room>&token=…
   ▼
Gateway  services/api/hootroute_api        relays, validates, persists. No walk logic.
   │  rooms.py     one room per walk: history for late joiners, fan-out, SQLite persistence
   │  contract.py  which role may send which message; agent message types are never accepted from clients
   │  db.py        walks, room history, GPS traces, alerts, shop declarations, audits, engine routes
   ▼
Agents   services/agents/hootroute_agents  Head (Claude) · Guide · Checker · Rescuer
   │  AGENT_RUNTIME=inprocess  (default) hosted inside the gateway
   │  AGENT_RUNTIME=uagents    hosted by services/agents/live_bureau.py as registered uAgents;
   │                           every hand-off between agents is a uAgents message
   ▼
Engine   services/engine/hootroute_engine  deterministic score, routing, "where", 311 lookups. No model, no crime input.
```

The agent code is the same in both runtimes. `Runtime.deliver()` (agent to agent) and `Runtime.route()` (room envelope to its owning agent) are the only parts `live_bureau.py` replaces.

## A walk, end to end

0. **Ask (optional).** `POST /api/head/ask {text, session?}`: Claude (the Head) resolves places, has the Guide plan, the Checker inspect the route and list unknown hours, optionally checks listings live and re-scores, then answers with a tool trace and a `planId`. `POST /api/check/route {planId}` is the Checker's inspection on its own; `POST /api/check/hours {planId}` the live Apify check.
1. **Plan.** `POST /api/plans {origin, destination, day?, minute?}` returns the route contract (`DemoData`) and a `planId`. Omitting the day and minute plans for now in San Francisco.
2. **Start.** `POST /api/walks {planId, origin, destination, choice, walker, guardian, guardianPhone?, thresholds, replay, timeScale}` returns `{walkId, walkerToken, guardianUrl}`. The walker's phone keeps the token; without it nobody can act as the walker. The guardian link carries only the walk id.
3. The **Guide** publishes `walk.plan` with the full route in `plan.data`. Every screen on every device draws from it, and a guardian who opens the link late gets it from the room history.
4. **Walk.** The walker sends `walk.accept`, `walk.start`, then `walk.position` (real GPS, or a labelled replay). The **Checker** computes progress itself from the coordinates, narrates turns, open places and empty stretches, and asks `checkin.ask` after `stopSeconds` still with no listed open place within 60 m. If the walker is more than 40 m off the route for 3 fixes, it asks **the Guide** to re-plan from where they are. It also detects arrival (25 m).
5. **Silence or Help.** The Checker hands off to the **Rescuer**, which sends `escalate` and `guardian.alert` (reverse-geocoded from the street graph, e.g. "Market St between Taylor St and McAllister St"), texts the guardian if Twilio is configured, and logs a handoff packet. Each `escalateSeconds` without an answer climbs one rung (`rescue.ladder`): call the guardian, text and call the backup contact, then show a Call 911 button to people. It never calls 911.
6. **Arrival.** The **Head** sends `walk.end` with a report Claude writes from the walk's facts, plus a DRAFT 311 note citing real open SF 311 case ids on the route. Nothing is submitted. Location stops being relayed and is dropped from the room history.
7. **Overnight.** The **Head** runs the overnight audit at 2:00 AM SF time (and on `audit.run` from the control room). It ranks streets by modeled walker-minutes on lower-light segments and drafts a 311 note citing real open case ids.

Shopkeepers call `POST /api/places/{id}/declaration {openUntil, safeHaven, frontLight}`. The declaration is stored until 6 AM, applied to every plan, and pushed as `place.update` to walks passing within 80 m. The Guide re-plans walks that haven't started and re-scores walks in progress.

Every automatic action is spoken (`voice.say`) or logged (`agent.log`) with a reason. The control room's feed is that log.

## Endpoints

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/api/health` | engine, runtime, SMS and voice availability |
| POST | `/api/plans` | Fastest vs HootRoute for any two points in SF |
| POST | `/api/walks` | create a walk; 201 with the walker token |
| GET | `/api/walks/{id}` | public status (no phone number, no token) |
| GET | `/api/walks?active=true` | control room; needs `X-Admin-Token` when `ADMIN_TOKEN` is set |
| GET / POST | `/api/places/{id}`, `/api/places/{id}/declaration` | shop page |
| GET | `/api/search`, `/api/why`, `/api/where`, `/api/debt`, `/api/audit/latest`, `/api/meta` | city layers |
| POST | `/api/voice/tts` | Cartesia Sonic proxy (501 when not configured; the PWA then speaks on-device) |
| GET | `/api/block-vision` | optional Mapillary + Claude explanation, never a score input |
| POST | `/api/internal/publish` | uAgents bureau only, with `X-Bridge-Secret` and agent message types only |
| WS | `/ws?walk&role&token` | rooms; unregistered ids are plain relays for the offline DemoEngine (`ALLOW_DEMO_ROOMS`) |
| POST | `/api/head/ask` | the Head (Claude): plain-language request → tool trace, answer, plan |
| POST | `/api/check/route`, `/api/check/unknowns`, `/api/check/hours` | the Checker: inspection, unknown-hours places, live Apify listing check + re-score |

## Security and privacy

- Clients can only send their own role's message types (`contract.py`). Agent messages (`walk.plan`, `checkin.ask`, `guardian.alert` and so on) from a client are dropped, and the gateway stamps `from` with the connection's role.
- The walker role needs the walker token from `POST /api/walks`. The control room needs `ADMIN_TOKEN` when one is set.
- Location is relayed only during a walk. After `walk.end` the room drops position history and refuses new positions. GPS traces of ended walks are deleted after `POSITION_RETENTION_HOURS`.
- The guardian's phone number never leaves the server and is not in any room message.
- Not done yet: shopkeeper accounts. Anyone who knows a place id can declare its hours. Put the shop page behind a per-shop link token before a public launch.

## Run

```bash
python3 -m venv .venv && .venv/bin/pip install -r services/requirements.txt
cd services/api && ../../.venv/bin/uvicorn main:app --port 8000 --reload --reload-dir . --reload-dir ../engine --reload-dir ../agents
cd web && npm install && npm run dev            # :5173, proxies /api and /ws to :8000
./scripts/fetch_tiles.sh                                    # once: SF basemap (needs `brew install pmtiles`)
```

Agents as uAgents (Fetch.ai):

```bash
python3 -m venv .venv-agents && .venv-agents/bin/pip install -r services/agents/requirements.txt
# repo .env: AGENT_RUNTIME=uagents and BRIDGE_SECRET=<random>; services/agents/.env: the seeds (see services/agents/README.md)
cd services/agents && ../../.venv-agents/bin/python live_bureau.py      # then restart the gateway
```

Python 3.14 works for both; `live_bureau.py` creates the event loop uAgents expects.

Tests (start real processes, about 1 minute): `.venv/bin/python -m pytest services/api/tests -q`. They cover planning, the walker token, forged-message rejection, stop, check-in, escalation, guardian ack, a shop declaration, arrival, the no-trace-after-end rule, the overnight audit, resuming a walk after a gateway restart, and the same walk under uAgents.

## Deploy (Vultr + Caddy)

`deploy/setup_vps.sh` on Ubuntu 24.04 with the repo at `/opt/hootroute`: venvs, PWA build, basemap, systemd units (`hootroute-gateway`, plus `hootroute-agents` when `AGENT_RUNTIME=uagents`), and Caddy for automatic HTTPS. Set `PUBLIC_URL`, `ADMIN_TOKEN` and `BRIDGE_SECRET` in `/opt/hootroute/.env`. The gateway serves the built PWA itself, so one domain carries the app, the API and the rooms.

Limits: one gateway process. Rooms and walk state are in memory, backed by SQLite, so run a single worker. Planning is serialised by the engine lock (about 1.5 to 3 s per plan).
