# Streetwise handoff: state, plan, where to start

Written Saturday Oct 24, 2026. Deadline: **Sunday Oct 25, 9:00 AM PT** (be at the venue by 8:00 AM). Read this first, then `README.md`.

## Decisions made

1. **Abhishek's frontend is the app.** `streetwise-web/` (React + Vite PWA, Figma tokens, five mascots, five screens) is the only frontend we build on. The earlier frontend is under `legacy/web/` as a reference until its offline basemap is ported.
2. **Trunk branch = `main`** on `StayJagrat/StreetWise` (Jagrat renamed Abhishek's `streetwise-web` branch to `main`; same commit `519db43`).
3. **Work in small pieces.** One branch per piece, named plainly after the piece (`gateway`, `live-mode`, not `feat/gateway`), one small PR into `main`, merged as soon as it runs. No long-lived branches. Rebase on `main` before opening a PR.
4. **Design = Abhishek's Figma build only.** Colours, type, mascots, spacing and screens come from `streetwise-web/` (`src/styles/tokens.css`, `public/mascots/`). Do not bring in our older amber/Lamp brand (`docs/BRAND.md`, `docs/brand-sheet.html`), `apps/web` styles, or placeholder avatars. New UI must use his tokens and components, and any new element gets approved by Abhishek in Figma first.
5. **Codex is in charge while Claude Code is at its usage limit.** Claude resumes after the reset; Codex should leave notes in this file (see "Log") so nothing is lost.
6. **Keys live in `.env`** (git-ignored), never in code or chat. The Anthropic, Apify, Creao and Fetch keys were printed once into a Claude session log: rotate them after the hackathon.

## What exists

| Part | Where | State |
| --- | --- | --- |
| Frontend (Figma-faithful) | `streetwise-web/` | Powell BART route plus searched destinations inside the pilot box. Offline replay and gateway mode are wired to `/ws`; local Protomaps tiles are used when present |
| Scoring engine, routing, steps, why-this-street, darkness debt, Watcher rules | `services/engine/` | Working, deterministic, tested on the downtown pilot box |
| Gateway (REST + one WebSocket room per walk) | `services/api/streetwise_api/` | Relay only: role checks, walker tokens, SQLite persistence, walks survive a restart. See `docs/BACKEND.md` |
| Live walk agents (Scout, Watcher, Rescuer, Reporter, Night Auditor) | `services/agents/streetwise_agents/` | Drive real walks: plan, narration, stop check-in, off-route re-plan, guardian alert + Twilio SMS, arrival, 311 drafts with real case ids. In-process by default; `live_bureau.py` runs the same code as registered uAgents |
| ASI:One chat agents | `services/agents/scout.py` etc. | 20/23 offline checks: the 3 that fail need a scenario where Streetwise and Fastest differ (they fail on `main` too since the citywide recalibration) |
| Hours pipeline (Apify + parser) | `services/hours/` | Real eight-category cache: 824 fetched records, 380 matched to OSM, 153 missing OSM schedules filled by the deterministic rules parser. Apify recorded $7.07 total against the $10 cap. Claude batch parsing was stopped because 374 source rows would make uncapped paid calls |
| Creao Hours Detective | `services/creao/` | Client and prompt done, key valid. No real run yet |
| Old frontend | `legacy/web/` | Superseded. Has a self-hosted offline basemap (PMTiles) worth porting |
| Data cache | `data/cache/` | Pilot box only: lat 37.784 to 37.794, lng -122.416 to -122.400 |
| Block imagery explanation | `services/api/vision.py` | Optional Mapillary + Claude endpoint; shows a missing-key state and sets `usedForScore: false` when imagery cannot be fetched |

## Citywide routing (done, Oct 24 afternoon). This replaces the old "demo corridor" decision.

The engine now covers all of San Francisco. Any start and destination works.
- **Data:** `scripts/build_city_cache.py` turns the BBBike SF extract (`data/raw/SanFrancisco.osm.pbf`, git-ignored; the download command is in that file) into `data/cache/osm_ways.json` and `osm_points.json`. The old pilot files are kept as `*_pilot.json`. SF 311 streetlight history is citywide (paged fetch in `scripts/fetch_data.py`).
- **Score calibration:** each walk is compared with typical walks in its own 2 km cell (`Norm` in `services/engine/streetwise_engine/scoring.py`), never the whole city, with floors on the spread so a dead area cannot saturate at 100. Cached in `data/cache/norms/`; `scripts/warm_norms.py` pre-computes them.
- **API:** `GET /api/route-demo?lat&lon&name&olat&olon&oname&day&minute` returns the app's `DemoData` for any two points, plus `options` and `recommended`. `GET /api/search?q=` is an offline search over places, streets and landmarks. A route in a new cell takes about 3 to 5 s, then about 1.5 s.
- **App:** new `/plan` screen (`streetwise-web/src/screens/Plan.tsx`): search or tap the map for start and destination, pick a departure time, compare Fastest and Streetwise scores, then "Review with Scout" opens `/walk` with that plan. The walk replay, check-in and escalation run on any route (checked in the browser on Powell St BART to Mission Dolores Park: 79 vs 97, +2.7 min).
- **Known limits:** places without listed hours count as closed (only 153 of 8,907 places have hours filled so far, so run Piece 6); the planner shows two options although the API also returns a `balanced` one; the gateway walk (`VITE_ENGINE=off`) and real GPS mode send the plan's start, destination and time but have not been re-tested on arbitrary routes; tests in `services/api/test_live_walk.py` were not re-run after the engine changes (pytest is not installed in `.venv`).

## The pieces, in order

Each piece ends with something you can see running.

### Piece 1: Import our backend (30 min)
Branch `backend-import`. Commit `services/`, `data/`, `docs/`, `research/`, `scripts/`, `README.md`, `.gitignore`, and move `apps/web` to `legacy/web`. Open a PR into the trunk. Check `git status` first; the hours raw files and `.env` are ignored.

### Piece 2: Gateway (1 h)
Branch `gateway`. Add `WS /ws?walk=<id>&role=<role>` to `services/api/main.py`, as in `streetwise-web/README.md` ("Wiring the gateway"):
- forward every envelope to everyone else in the walk's room;
- on join, send `{kind:"history", envelopes:[...]}`;
- keep the old `/ws/{session}` working until the old frontend is deleted.
Point `streetwise-web/vite.config.ts` `/ws` proxy at `127.0.0.1:8000` instead of the relay on 8787. Test: `/room` on one tab and `/walk` on another see each other's messages.

### Piece 3: Real route plan (2 h)
Branch `engine-demo-data`. Add `GET /api/demo` that returns Abhishek's `DemoData` shape (`streetwise-web/src/lib/types.ts`) built from the engine: `route`, `shortest`, `dimStretches` (with `lampEvidence`, `openPlaces`, `why`), `places`, `stats` (score, longest empty stretch, minutes for both routes), `darknessDebt`. Write the result to `streetwise-web/public/data/demo-route.json` so the demo works offline, and keep the endpoint for live mode. Numbers on stage must come from the engine, not the placeholder 60 vs 49.

### Piece 4: Live mode, agents drive the walk (3 h) — DONE on `live-backend`, see docs/BACKEND.md
Branch `live-mode`. With `VITE_ENGINE=off`, the backend answers client messages with agent messages:
- `walk.accept` → `walk.plan` (+ `voice.say` from Scout, `agent.log` with `reason`)
- `walk.position` → Watcher rules (`watcher_decide` in the engine) → `checkin.ask`, then `escalate` and `guardian.alert` on silence
- `checkin.reply` → clear the alert
- `place.update` → re-score the route, send a new `walk.plan` plus `agent.log`
- `audit.run` → `audit.result` (ranking and the draft 311 text; nothing is ever submitted)
Reuse thresholds from `walk.plan.plan.thresholds` (default 90 s stop, 45 s reply, 90 s escalate).

### Piece 5: Fetch.ai on Agentverse (2 h) — code done (`live_bureau.py`, tested locally); still needs the seeds and the Agentverse mailbox connect
Branch `agentverse`. Follow `services/agents/README.md`: fill the 8 seeds in `services/agents/.env`, run `run_all.py`, connect the Scout mailbox in Agentverse, confirm Scout answers in ASI:One chat. Make the gateway agents and the uAgents the same logic, called from both (do not fork it). README needs each agent's name, address and the Innovation Lab badges. Get the submission agent address from the Fetch resources doc.

### Piece 6: Real hours (2 h, run in the background)
Branch `hours-run`. Dry run first, then:
```bash
cd services/hours && ../../.venv-hours/bin/python run_pipeline.py --dry-run --categories restaurant,bar,cafe,"fast food restaurant","convenience store",pharmacy,pub,"liquor store",bakery --budget-usd 10
```
Remove `--dry-run` once the cost looks right. Check why only 3 of 10 places matched OSM (`match_osm.py` distance and name thresholds). Then `evaluate.py --parser claude` for an accuracy number, and run 3 places through Creao (`creao_client.py --limit 3`) to get the run share link for the README.

### Piece 7: Map polish (1 h)
Branch `map-offline`. Port the self-hosted Protomaps basemap from `legacy/web` into `streetwise-web/src/lib/mapStyle.ts` (keep his `map/*` Figma colours). OpenFreeMap tiles need the network; venue Wi-Fi is the biggest demo risk. Run `./scripts/fetch_tiles.sh` on every demo laptop.

### Piece 8: Search and the Google-style comparison (2 h)
Branch `search-and-baseline`.
- Destination search with the keyless Photon geocoder (`photon.komoot.io`), limited to the SF area, in Abhishek's Setup screen style.
- The "usual route" line: OSRM walking route (keyless), scored by our engine at the same minute, so the stage comparison is "what a map app sends you" versus Streetwise on the same formula.

### Piece 9: Look at the block, Claude vision on Mapillary (2 h)
Branch `block-vision`. For a dim stretch, fetch the nearest Mapillary street-level image (free key) and have Claude (`claude-sonnet-5-5`) describe what is visible in two plain sentences: lamps, shuttered or lit storefronts, scaffolding. Show it on the existing dim-stretch card with the capture date. **Explanation only, never an input to the score.** Say when no recent image exists. Do not cache or show Google Street View.

### Piece 10: Hills, transit and events (3 h, in this order, stop when time is short)
- Branch `hills`: elevation from Open-Meteo. Add a "flatter route" option and slope in the ETA. Steps and stairs from OSM stay as they are.
- Branch `transit-live`: 511.org real-time arrivals for the transit input (free key). Fall back to the BART schedule we already use.
- Branch `events`: Ticketmaster Discovery API (free key) for shows letting out near the route. Start as an agent note ("Orpheum lets out about 11:15 PM"); only make it a score input if it is documented in the formula and tested.
Each new signal needs a line in the formula docs and a "data missing" state.

### Piece 11: Proof and submission (rest of the night)
- Field walk: walk the demo route near 11 PM if possible; count open places and lit gaps versus the prediction. One honest number for the pitch.
- Anthropic track: pick the named community and confirm the rubric at the booth. Figma and MLH rubrics too.
- Rename or subtitle: a Paris app is also called "Streetwise".
- README with run steps, Devpost text, 3 to 5 min video, 3 min pitch, public repo with no keys, Creao agent ID and run link.

## Demo-day numbers to protect
The old "63 vs 57" came from pilot-box data. On the citywide engine (Friday 11:04 PM, current hours evidence) the stage corridor Powell BART → Transamerica Pyramid scores 86 vs 85, which no longer makes the point. A scan of landmark pairs found stronger corridors (Fastest → Streetwise, longest empty stretch, extra time):

| Corridor | Score | Longest empty stretch | Extra |
| --- | --- | --- | --- |
| Moscone Center → City Hall | 57 → 77 | 560 m → 390 m | +1.1 min |
| Moscone Center → Ferry Building | 30 → 66 | 1710 m → 700 m | +4.8 min |
| Powell St BART → Salesforce Transit Center | 60 → 82 | 290 m → 320 m | +0.0 min |

To switch the stage corridor, change `ORIGIN` and `DESTINATION` in `services/agents/streetwise_agents/plan_data.py`, then run `scripts/export_demo.py`. Re-check the numbers after any hours-evidence change. The score uses no crime data and no model. Always say "conditions, not a safety rating".

## Run it locally

See [BACKEND.md](BACKEND.md#run). Short version: `cd services/api && ../../.venv/bin/uvicorn main:app --port 8000 --reload`, then `cd streetwise-web && npm run dev`. Run `./scripts/fetch_tiles.sh` once for the basemap.

## Rules we keep
- Nothing in the score comes from a model. Models explain, plan and parse; they never change a number.
- Nothing calls 911 and nothing is submitted to the city. Demo shops are labelled simulated.
- Say when data is missing. Never write "safe", "unsafe", "dangerous" or "sketchy".

## Log (add a line per finished piece; newest last)
- 2026-10-24: Trunk is `main`. Local branch `backend-import` holds Abhishek's commit plus our uncommitted backend. Nothing committed or pushed from our side yet.
- 2026-10-24: Piece 1 prepared on `backend-import`: moved the earlier frontend to `legacy/web`, staged the backend and supporting files, updated the root README and ignores, and confirmed the restarted API returns HTTP 200 in the browser. User committed as `baf7e34`.
- 2026-10-24: Piece 2 prepared on `gateway`: FastAPI now relays walk envelopes at `/ws`, replays room history to joiners, and keeps `/ws/{session}`. Vite proxies `/ws` to port 8000. Confirmed forwarding, history, legacy WebSocket, a production frontend build, and linked `/room` and `/walk` browser views. User committed as `aa4b517`.
- 2026-10-24: Piece 3 prepared on `engine-demo-data`: Powell BART → Transamerica Pyramid route and shortest path now come from the deterministic Python engine and cached OSM/SF 311/BART data. `/api/demo` and offline JSON match exactly: score 55 vs 49, empty stretch 450 vs 650 m, 21.2 vs 18.0 min; simulated Walgreens hours update has an engine-calculated fixed-route what-if of 69 vs 60. Verified export, build, API, `/walk`, `/shop`, and `/room` with the route evidence card in the browser. Map tiles still need a connection or prior cache. Commit awaits the user.
- 2026-10-24: Integration pass on `engine-demo-data`: `/ws` now activates the deterministic live-walk adapter, supports selected destinations snapped within 150 m, and refuses to start a fallback route when planning fails. Verified the browser control room, replay movement, dim-stretch Watcher check-in, guardian escalation link, route search, local Protomaps map, and a custom-destination walker route. After importing real hours evidence, the offline export and API match at 63 vs 57, 230 m vs 510 m empty stretches, and 21.1 vs 18.0 minutes; the engine reports 153 added schedules and 339 places whose hours remain missing. The eight-category Apify cache cost $7.07 total, under the $10 cap; the source rules parser processed 380 OSM matches. A 40-place parser evaluation measured 95.1% weekly half-hour-slot agreement (62.5% of the sample reached at least 95%). Build and 7 unit tests pass. Agentverse still needs the eight account seeds; live Mapillary, 511, and Ticketmaster features need provider keys. No Agentverse deployment or field walk was performed. No commit or push.
- 2026-10-24 PM: Codex built the gateway, live walk, vision and demo export on `engine-demo-data`. Claude added citywide data, regional score calibration, `/api/route-demo` for any two points, `/api/search` and the `/plan` screen. Committed and pushed on `engine-demo-data`; open a PR into `main`.
- 2026-10-24 evening (Claude, branch `live-backend`): restructured the backend. The gateway (`services/api/streetwise_api/`) is relay-only, with role-checked messages, walker tokens and SQLite persistence. The five agents (`services/agents/streetwise_agents/`) drive real walks, in-process or as uAgents (`live_bureau.py`, every agent-to-agent hand-off is a uAgents message). The PWA creates walks with `POST /api/walks` and every screen draws Scout's `walk.plan` (fixes the guardian QR showing the wrong route on another phone). Flags: `?agents=live|demo`, `?gps=real|replay`. Added Twilio SMS backup, Cartesia Sonic proxy, cross-street "where" for alerts, 311 drafts citing real open case ids, off-route re-plan, arrival detection, map error boundary (no WebGL no longer blanks the app), Logo and favicon from Abhishek's copy, deploy files for Vultr + Caddy. Tests: 4 end-to-end in `services/api/tests` (including restart and uAgents). Re-exported `demo-route.json`: the committed one was from pilot-box data; on the citywide engine Powell → Transamerica is now 86 vs 85.
- 2026-10-24 night (Claude, branch `four-agents`): renamed the product **HootRoute** (`APP_NAME`/`VITE_APP_NAME`), owl logo and icons. Four agents: **Head** (Claude tool use: `head_brain.py`, `POST /api/head/ask`, end-of-walk report), **Guide** (was Scout), **Checker** (was Watcher, plus `hours_check.py`: unknown-hours places and a live Apify listing check, `POST /api/check/unknowns|hours`), **Rescuer** (ladder: live link + SMS → call → backup contact → Call 911 button; never dials 911). Reporter and Night Auditor merged into Head. ASI:One front door is `services/agents/head_chat.py`; old chat agents moved to `services/agents/legacy_chat/`. Stage corridor Moscone Center → City Hall, Fri 11:30 PM: 77 vs 57. Stage replays start 300 m before the stop. Abandoned walks expire. 6/6 gateway tests pass. See `docs/SUBMISSION.md`.
