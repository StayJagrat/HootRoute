![tag:innovationlab](https://img.shields.io/badge/innovationlab-3D8BD3)
![tag:hackathon](https://img.shields.io/badge/hackathon-5F43F1)

# HootRoute

**Your night shift has a wingman.** HootRoute is a walking companion for **San Francisco late-shift workers** (hospitality, service and healthcare staff) walking from work to transit or home after 11 PM. Built at Cal Hacks 13.0.

Map apps send you the fastest way. At 11:30 PM the fastest way is often the emptiest: the cafés that lit it at 6 PM are shut, and the map doesn't know. HootRoute scores every block by **what is listed open, lit and reachable at the minute you pass it**, checks what it doesn't know, walks with you, and brings in your people only if you stop and don't answer.

**Conditions, not a safety rating.** No crime data goes in. No model produces a number. HootRoute never calls 911.

## Four agents

| Agent | Mascot | Job | Built with |
|---|---|---|---|
| **Head** | moth | Understands your request in plain words, delegates to the others, explains the result, writes your end-of-walk report, runs the overnight audit | Claude (tool use), Fetch.ai uAgents + ASI:One |
| **Guide** | pigeon | Plans the fastest route and the HootRoute route and scores both at the minute you pass each block; re-plans if you leave the route or a shop updates its hours | Deterministic Python engine (NetworkX, NumPy), OSM, SF 311, BART |
| **Checker** | raccoon | Before you leave: the score breakdown and the places on your route whose hours are unknown, then a **live listing check** that the Guide re-scores with. During the walk: notices a stop on a stretch with nothing open and checks in | Apify (Google Maps actor), deterministic hours parser |
| **Rescuer** | sea lion | If you don't answer: live map link + SMS to your guardian → phone call → backup contact → a **Call 911 button** for people. It never dials 911 itself | Twilio |

```
PWA (walker · guardian · shop · control room)        ASI:One chat
        │ REST /api/head/ask /api/plans /api/check/*        │ Agent Chat Protocol
        │ WS   /ws?walk&role&token                          ▼
        ▼                                            hootroute-head (uAgent, Agentverse)
  Gateway (FastAPI) ── rooms, SQLite ──────────────────────┘
        │
  Head (Claude) ──tools──> Guide: find_place, plan_routes, rescore_routes
        │                  Checker: find_route_unknowns, check_listed_hours (Apify)
        ▼
  Walk agents: Guide · Checker · Rescuer · Head   (in-process, or as uAgents via live_bureau.py)
        │
  Engine (deterministic score, routing, 311 lookups)  ── no model, no crime input
```

## Run it

```bash
python3 -m venv .venv && .venv/bin/pip install -r services/requirements.txt
cp .env.example .env        # fill in what you have; every provider is optional
cd services/api && ../../.venv/bin/uvicorn main:app --port 8000          # gateway + agents
cd streetwise-web && npm install && npm run dev                          # PWA on :5173 (proxies /api and /ws)
```

Open `/` for the hub, `/plan` to ask the Head, `/room` for the control room (its QR code opens the guardian view on a second phone). For HTTPS to a phone: `cloudflared tunnel --url http://localhost:5173`. Deploy: `deploy/setup_vps.sh` (Vultr + Caddy).

Keys (all optional, in the git-ignored `.env`): `ANTHROPIC_API_KEY` (Head), `APIFY_TOKEN` (live hours check), `TWILIO_*` (texts and calls), `CARTESIA_API_KEY` (voice), `MAPILLARY_TOKEN` (street imagery explanation). Without a key each feature says "not configured" and the walk carries on.

Tests: `.venv/bin/python -m pytest services/api/tests -q` (6 end-to-end tests: planning, walker token, forged messages, check-in, the full rescue ladder, the Head and the Checker, restart recovery, and the same walk under uAgents).

## Sponsor tracks

### Fetch.ai: the whole workflow in ASI:One
`hootroute-head` speaks the Agent Chat Protocol. In one ASI:One conversation: describe the walk → the Head has the Guide plan and score both routes and the Checker list unknown-hours places → **"check the hours"** runs a live Apify check and re-scores → **"start my walk"** returns the walker and guardian links. The four agents also run real walks as uAgents (`services/agents/live_bureau.py`): every hand-off (Checker → Rescuer, Checker → Head, Checker → Guide) is a uAgents message checked against the sender's address.

| Agent | Address |
|---|---|
| hootroute-head | `TODO: python services/agents/print_addresses.py --md` |
| hootroute-guide | |
| hootroute-checker | |
| hootroute-rescuer | |

Setup: `services/agents/.env` with the four seeds, `python head_chat.py`, open the inspector link it prints, **Connect → Mailbox**.

### Anthropic: Claude for a named community
Named community: SF late-shift hospitality, service and healthcare workers walking after 11 PM. Claude is the Head: it reads a plain request, chooses tools (`find_place`, `plan_routes`, `find_route_unknowns`, `check_listed_hours`, `rescore_routes`), and explains. **Where it could go wrong, and what we did:** it could invent numbers (every number must come from a tool result; the trace shows each call), call "unknown" hours "closed" or call a street "unsafe" (prompt rules plus a filter on banned words), loop or stall (max 8 tool calls, 150 s deadline, schema checks on arguments), or be unavailable (a fixed pipeline runs and says so). Claude also writes the end-of-walk report from the walk's facts only.

### Apify
The Checker runs `compass/crawler-google-places` live (`services/agents/streetwise_agents/hours_check.py`) on places along your route whose hours are unknown, matches listings by name within 80 m, parses the hours deterministically, and the Guide re-scores. Before/after is shown in the app with the source and time. The citywide hours cache came from the same actor (`services/hours/`, $7.07).

### Cartesia
Voice is the walking interface: the Guide speaks turns, the Checker asks "You stopped. All good?" and the walker answers out loud. Sonic is proxied by the gateway (`/api/voice/tts`, key stays server-side) and falls back to on-device speech. Limits: speech input uses the browser's recognizer today.

### Figma
One variable set (`streetwise-web/src/styles/tokens.css`) drives every screen; mascots and the logo come from the Figma file. See `docs/SUBMISSION.md` for the stage log.

## Honesty rules
Demo replays carry a "DEMO · GPS REPLAY" tape. Simulated shops are labelled. Unknown hours are shown as unknown. 311 reports are drafts with real case ids and nothing is submitted. The guardian sees location only during an active walk; GPS traces are deleted after 24 h. HootRoute never dials 911; the last rung is a button a person presses.

## Layout
`streetwise-web/` PWA · `services/api/` gateway · `services/agents/` agents (`streetwise_agents/` walk logic, `head_chat.py` ASI:One, `live_bureau.py` uAgents) · `services/engine/` scoring · `services/hours/` hours pipeline · `data/cache/` city data · `deploy/` Vultr + Caddy · `docs/` handoff and submission kit.
