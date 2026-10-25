# HootRoute architecture

HootRoute is one journey platform for people walking in San Francisco after dark: students leaving late classes and
late-shift workers. It compares routes by documented conditions at the minute you pass each block, investigates what it
does not know, and stays with you when the plan changes. **Conditions, not a safety rating.**

```
web/ (React + Vite PWA, MapLibre)                         ASI:One chat (Fetch.ai)
  /plan  Professor Hoot panel · Evidence Explorer ·        services/agents/head_chat.py
         Mission Control · route preferences                      │ HTTP
  /walk  live journey · report a problem · recovery ·             │
         sharing on/off · check-in ladder                         │
  /guardian/:walk?g=<token>   /room (control room)                │
        │ REST + WS /ws?walk&role&token                           │
        ▼                                                         ▼
services/api/hootroute_api   gateway: validation, roles, rate limits, SQLite, walk rooms
        │
        ├── Professor Hoot (head_brain.py)  Claude tool use: picks tools, proposes paid checks, explains,
        │                                   numbers_check() verifies every number against tool results
        ├── Scoot McRoute  (engine_port, plan_data, preferences.py)   deterministic routes, scores, preference ranking,
        │                                   re-plans around reported obstacles (engine.route(avoid=...))
        ├── Sherlock Hoots (hours_check.py, evidence.py, inspect_route.py)  unknown hours, Apify run after approval,
        │                                   evidence with source / time / run id, reuse within TTL, daily budget
        └── Wingman Wally  (agents.py Rescuer + runtime.contact)  obstacle reports → recovery options → walker's choice,
                                            sharing on/off, check-in ladder; SMS/calls only with opt-in
        │
services/engine/hootroute_engine   deterministic score over OSM (139,515 segments, 8,907 places), SF 311 lights,
                                   BART schedule, SFMTA closures. 10 m sampling, hours evaluated at arrival minute.
```

## Decision boundaries

| Decision | Who decides | Enforced in |
|---|---|---|
| Route scores, minutes, distances | Python engine only | `hootroute_engine/scoring.py`; Claude's prose is checked by `numbers_check` and replaced if it states a number no tool produced |
| Which tools to call, what to investigate | Claude (Professor Hoot), or the fixed pipeline without a key | `head_brain.py` |
| Spending money on a listing check | The walker | Claude can only call `propose_hours_check`; `/api/head/approve` runs exactly the approved places; `/api/check/hours` requires `confirm: true`; daily budget + $0.50 cap per run |
| Changing the active route mid-walk | The walker | `recovery.options` is a proposal; only `recovery.choose` switches |
| Who sees the live position | The walker | guardian link token, `POST /api/walks/{id}/share` revokes it and disconnects guardians |
| Texting or calling contacts | The walker's opt-in (`notifyConsent`) | `Runtime.contact`: consent, sharing on, allowlist, per-walk cap, emergency numbers refused |
| Contacting emergency services | A person, never the app | the last ladder rung is a Call 911 button |

## Evidence lifecycle (Sherlock Hoots)

1. `find_route_unknowns`: named places on the route with no hours (they earn no credit in the score; shown as unknown, never closed).
2. `propose_hours_check` → `pendingApproval` (places, provider, cost cap, reason).
3. Approval → `hours_check.investigate`: reuse checks younger than `EVIDENCE_TTL_HOURS`, spend one Apify run on the rest
   (`run_actor`: start run → wait → abort on timeout → dataset), parse hours deterministically, match by name within 80 m.
4. Each result becomes `Evidence {kind, hours, source{provider,url,runId,consoleUrl}, retrievedAt, stale, reused, confirmedOpenNow:false}`
   and is stored in `data/cache/hours_live.json` (git-ignored). Failed checks are not stored; mock results are never stored.
5. Found hours are applied to the engine; Scoot re-plans; Hoot explains before/after, or why nothing changed.
6. `GET /api/plans/{id}/evidence` shows every place on the route with its provenance: OSM tag, overnight Apify batch, live check, shopkeeper declaration, or none.

## Mission Recovery (Wingman Wally)

`obstacle.report` (walker) → Wally logs it and tells Hoot → Hoot asks Scoot for routes from the walker's position that
avoid 35 m around the spot just ahead (`engine.route(avoid=...)`: those segments cost 10,000×; the score never sees it) →
Hoot explains (Claude with numbers check, or a template) → `recovery.options {current, options[], explanation}` → walker
sends `recovery.choose` → Scoot promotes the chosen candidate to the active route and publishes `walk.plan`
("Switched after your report …"). Options expire after 5 minutes. Hours evidence gathered earlier is reused; no paid
check runs during a walk.

## State

SQLite (`DB_PATH`): walks (tokens, contacts, consent, sharing), room history (no positions), GPS fixes (purged 24 h after
the walk ends), alerts, shop declarations (expire 6 AM), audits, routes. In memory: agent walk state (rebuilt from
history on restart), Hoot sessions (1 h), plan cache (30 min), pending approvals (10 min), pending recovery options (5 min).

## Security defaults

Rate limits per IP; `HOOTROUTE_ENV=production` refuses to start without `ADMIN_TOKEN`, an https `PUBLIC_URL`, explicit
`CORS_ORIGINS`, and `SMS_ALLOWLIST` when Twilio is set; `AGENT_RUNTIME=uagents` refuses to start without a 16+ character
`BRIDGE_SECRET` (gateway and bureau). Tokens in WebSocket query strings are redacted from uvicorn logs. Shop declarations
need the admin token in production (no shopkeeper accounts yet).

Full wire contract: [AGENT_API.md](AGENT_API.md). Older endpoints: [BACKEND.md](BACKEND.md).
