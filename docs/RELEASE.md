# HootRoute: setup, demo walkthrough, release checklist, sponsor status

Status as of Sat Oct 24 2026, branch `agentic` (local, not pushed). Deadline Sun Oct 25, 9:00 AM PT.

## Setup

```bash
python3.12 -m venv .venv && .venv/bin/pip install -r services/requirements.txt pytest websockets
cp .env.example .env              # fill in only what you have; every provider is optional
cd services/api && ../../.venv/bin/uvicorn main:app --port 8000
cd web && npm ci && npm run dev   # http://localhost:5173 (proxies /api and /ws to :8000)
./scripts/fetch_tiles.sh          # once per demo laptop: offline SF basemap (needs `brew install pmtiles` + network)
```

| Key in `.env` | Turns on | Without it |
|---|---|---|
| `ANTHROPIC_API_KEY` | Professor Hoot on Claude (`HEAD_MODEL`, default `claude-sonnet-5-5`) | fixed pipeline, labelled in the UI |
| `APIFY_TOKEN` | live listing checks after approval | approval card shows "unavailable"; hours stay unknown |
| `TWILIO_*` + `SMS_ALLOWLIST` | texts and calls to opted-in contacts | live link only |
| `CARTESIA_API_KEY` | server voice | on-device speech |
| `MAPILLARY_TOKEN` | street-image explanation | "missing key" state |
| `HOURS_CHECK_MOCK=1` | labelled offline stand-in for Apify (rehearsal only, never saved) | — |

uAgents / Agentverse: `services/agents/README.md` (needs `HEAD_SEED`… in `services/agents/.env`, `BRIDGE_SECRET` of 16+ characters).

Tests:
```bash
.venv/bin/python -m pytest services/api/tests -q          # 21 tests, ~2 min, starts real gateway processes
cd services/hours && ../../.venv/bin/python -m pytest tests -q
cd services/creao && ../../.venv/bin/python -m pytest test_creao_client.py -q
cd web && npx tsc --noEmit && npm run build
```

## Demo walkthrough (golden workflow, ~3 min)

Stage corridor: Moscone Center → City Hall, Friday 11:30 PM (engine: HootRoute 77 vs fastest 57, longest stretch with
nothing listed open 390 m vs 560 m). Re-check after any hours-evidence change.

1. Open `/`. Type to Professor Hoot: "from Moscone Center to City Hall Friday at 11:30 pm, fewer turns, check listed hours".
2. Hoot's answer quotes engine numbers ("Numbers match tool results"); routes appear on the map and in **Routes**.
3. Sherlock's card asks for your OK with the places and the $0.50 cap. Nothing has run yet. Press **Run check**:
   before → after scores, run id and Apify console link. **Evidence** shows every place, its source and time; unknown stays unknown.
4. **Agents** tab: every tool call, which persona ran it, why, timing, parallel calls marked.
5. **Start with HootRoute** → optional contact, opt-in for texts, "Demo: replay GPS" on → **Start journey**.
6. Live: turn banner, minutes left, score. **Report a problem ahead → Construction → Find another way**: Mission Recovery
   compares your route with alternatives; nothing switches until you press **Switch to this route**.
7. Toggle **Share live location** off: the guardian link (`/guardian/<id>?g=…`) shows "Sharing was stopped".
8. Close on the rules: conditions, not a safety rating; no crime data; no model in the score; never calls 911.

The replay is labelled "GPS replay · demo" on screen. Say so.

## Release checklist

- [ ] `.env` on the demo laptop: `ANTHROPIC_API_KEY`, `APIFY_TOKEN` (and Twilio only if you will show texts).
- [ ] Run the golden workflow once with real keys; screenshot the Apify console run and Mission Control trace.
- [ ] The basemap loads from Geoapify (`VITE_GEOAPIFY_KEY`) or CARTO (no key). Without internet the routes still draw on a plain background.
- [ ] Full test suite green on the final commit (commands above).
- [ ] Public deploy only with `HOOTROUTE_ENV=production`, `ADMIN_TOKEN`, https `PUBLIC_URL`, `CORS_ORIGINS`, `SMS_ALLOWLIST`; the gateway refuses to start otherwise.
- [ ] Rotate the keys HANDOFF says were printed into an earlier session log.
- [ ] README: agent addresses (`python services/agents/print_addresses.py --md`), CREAO agent id + run link, video link.
- [ ] Devpost text matches what runs (see `docs/SUBMISSION.md`; update its agent names to the personas if you keep them).

## Sponsor status (factual)

| Track | Done and verified | Still needed (who) |
|---|---|---|
| Anthropic, Claude for Public Benefit | Tool-use orchestration with approval gate, concurrent read-only calls, recovery coordination, numbers check; verified with a scripted model in tests and the fixed pipeline in the browser | **One real run with `ANTHROPIC_API_KEY`** (you); record the trace |
| Apify | Run start → wait → abort-on-timeout → dataset, run id + console URL stored with each result; tested with a mocked HTTP transport; earlier real runs exist in the batch evidence | **One real approved check** with `APIFY_TOKEN` (you); screenshot the console run |
| Fetch.ai | `head_chat.py` speaks the Chat Protocol and now handles approve/skip; `live_bureau.py` runs the four agents as uAgents (test passes locally) | Seeds, Agentverse mailbox, ASI:One conversation, addresses in README, submission agent (you). **Not eligible to claim until verified in ASI:One** |
| CREAO | Client and prompt exist (`services/creao/`), tests pass | A real run, the agent id and the run share link. It is not called at runtime; don't claim it is foundational |
| Figma | Abhishek's design system kept (tokens, mascots, logo); new panels reuse it | Abhishek to review the new panels; stage log in SUBMISSION.md |
| Microsoft / People-First | Consent-based sharing, opt-in notifications, revocable links, unknown shown as unknown | Opt in on Devpost |
