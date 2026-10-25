# What was fixed (branch `agentic`, Oct 24 2026)

Two commits on top of `main` (`ef882b1`): `c92dc5e` (agentic backend + security) and `b468334` (new frontend).

## Backend

**Security (release blockers)**
- Paid checks need approval. `allowChecks` defaults to false and is ignored unless the control-room token is sent. Claude can only *propose* a check (`propose_hours_check`); `POST /api/head/approve` runs exactly the approved places. `POST /api/check/hours` returns 428 without `confirm: true`.
- Removed the no-key regex that started a paid Apify run whenever a request contained the word "open".
- Guardian links carry their own random token (`/guardian/<id>?g=<token>`). The walk id alone no longer opens the live view, sends "I'm on it" or reads `GET /api/walks/{id}`.
- `POST /api/walks/{id}/share` (walker token only) stops sharing: the token is revoked, guardian sockets are disconnected, and a new link is issued if sharing is turned back on. This also re-checks the token after a socket joins, which closes a race.
- SMS and calls go through one gate (`Runtime.contact`). The walker must opt in (`notifyConsent`) and sharing must be on. Optional `SMS_ALLOWLIST`, a per-walk cap, and emergency numbers are refused.
- Bridge secret: `AGENT_RUNTIME=uagents` refuses to start without a 16+ character `BRIDGE_SECRET` (gateway and bureau), and an empty secret is never accepted. This fixes the forged-alert bug.
- `HOOTROUTE_ENV=production` refuses open defaults: `ADMIN_TOKEN`, an https `PUBLIC_URL`, explicit `CORS_ORIGINS`, and `SMS_ALLOWLIST` when Twilio is set. Shop declarations need the admin token there.
- Per-IP rate limits on planning and every paid endpoint (429 with `Retry-After`), plus a daily cap on Apify runs. Walker, guardian and admin tokens are redacted from uvicorn logs.

**Agents**
- Professor Hoot keeps a typed trace for every tool call (persona, why, status, timing). Independent lookups run in parallel and the trace keeps Claude's call order.
- `numbers_check` checks every number in Claude's answer against the tool results and swaps in an engine summary if one doesn't match.
- New tools: `rank_by_preferences` (deterministic choice among the engine's candidates) and `replan_avoiding` (re-plan around a reported spot).
- Sherlock Hoots, evidence handling:
  - Apify runs record the run id and console link, and a run that times out is aborted.
  - Every result is an `Evidence` record with its source and time (`confirmedOpenNow` is always false).
  - Recent checks are reused instead of re-billed; failed and mock results are never stored.
  - `GET /api/plans/{id}/evidence` shows where each place's hours came from.
- Scoot McRoute: `engine.route(avoid=...)`. Normal plans are unchanged, and the stage route still scores 77 vs 57. The balanced route can now be walked.
- Wingman Wally, Mission Recovery:
  - `obstacle.report` leads to `recovery.options`, then `recovery.choose`. The route never switches without the walker's choice.
  - A stale or unknown choice gets `recovery.closed`.
  - There is a 30-second cooldown between reports.
  - After a restart, the walk follows the route the walker chose.
- The ASI:One chat agent asks "approve" or "skip" before a paid check.

**Correctness**
- Unknown hours are shown as unknown, never "closed". A place whose listed hours are closed when you pass shows "closed" instead of a wrong "open till" time.
- Runtime files (`hours_live.json`, new score-norm files, the database) are git-ignored.

**Tests:** 21 gateway tests (6 existing, updated; 15 new) cover the approval gate, guardian tokens and revocation, notification gating, numbers check with a scripted Claude, evidence, recovery, preferences and security settings. Hours tests: 10. CREAO tests: 2.

## Frontend

**Why the old UI kept coming back**
- The map loaded `/tiles/sf.pmtiles`, which was never downloaded, so every screen sat on a blank canvas. It now uses Geoapify (`VITE_GEOAPIFY_KEY`) or CARTO's keyless dark map, and still draws routes on a plain background when offline.
- The PWA service worker served cached copies of old builds. It's now set to remove itself and clear those caches.
- Hardcoded demo content was removed: the crew hub, intro, setup, shopkeeper and control-room screens, the scripted demo engine (`?agents=demo`) and the cached `demo-route.json` loader.
- Arrival time was computed from the current time instead of the departure time (the "arrive by 8:28 PM" on an 11 PM walk). Fixed.

**New UI ("Nocturne")**: `web/src/styles/theme.css`, with three screens.
- `/`: ask Professor Hoot, or set from, to, time and preferences. Routes are drawn on the map. Sherlock's approval card shows the places and the cost cap. There are Routes, Evidence and Agents tabs, and every number comes from the API.
- `/walk`: turn banner, minutes left, report a problem, Mission Recovery comparison, a sharing toggle with "Send link", check-in, and a Call 911 button you press yourself. GPS replay is labelled on screen.
- `/guardian/:walk`: the trusted contact's live view, with a "Sharing was stopped" state.
- One `.env` at the repo root; Vite exposes only `VITE_*` values.

**Checks:** `tsc` and the production build pass. The full flow was run in the browser: ask → approve → start → report → switch route.

## Still needs keys or people
- A real Claude run (`ANTHROPIC_API_KEY`) and a real approved Apify check (`APIFY_TOKEN`).
- Fetch.ai: seeds, Agentverse mailbox, and a verified ASI:One conversation.
- CREAO: a real run, the agent id and the share link.
- Abhishek should know that the design changed.
- Not upgraded yet: MapLibre (4 → 6) has a critical advisory, but the fix is a breaking upgrade.
