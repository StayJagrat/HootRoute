# HootRoute: Claude Code instructions

Read `AGENTS.md` (product rules, design, repo), then `docs/ARCHITECTURE.md` and `docs/AGENT_API.md`. Release steps and
sponsor status: `docs/RELEASE.md`. Trunk is `main` on `StayJagrat/HootRoute`.

## Hard rules
- Do not commit, push, pull, rebase, reset or switch branches unless the user asks. Never force-push or deploy.
- Scores come only from `services/engine`. Claude chooses tools and words; `numbers_check` in `head_brain.py` must keep passing. Never add a model to the score.
- Paid or consequential actions need the walker's approval: Apify checks go through `propose_hours_check` → `/api/head/approve` or `/api/check/hours` with `confirm: true`; texts and calls only through `Runtime.contact` (opt-in, sharing on, allowlist, cap). Nothing dials 911 or submits to the city.
- Copy: "conditions, not a safety rating". Never write safe, unsafe, dangerous, sketchy. Unknown hours are unknown, never closed. Published hours are not proof a place is staffed. Label mock, replay and simulated data.
- Secrets live only in the git-ignored `.env`. Never print, log or `source` it.
- Design: the "Nocturne" system in `web/src/styles/theme.css` (ink, glass panels, moon = your route, mint = listed open, amber = unknown/decision, red = urgent only). Three screens: `/` plan (`pages/Plan.tsx`), `/walk` live journey, `/guardian/:walk`. No mascots, no new UI libraries. Persona names live only in `web/src/lib/personas.ts` and `services/agents/hootroute_agents/brand.py`.
- Internal agent ids stay `head | guide | checker | rescuer` (messages, mascots, uAgents seeds).

## Run and test
- Gateway: `cd services/api && ../../.venv/bin/uvicorn main:app --port 8000` · Web: `cd web && npm run dev`. One `.env` at the repo root serves both (Vite reads only `VITE_*`).
- `.venv/bin/python -m pytest services/api/tests -q` (21 tests, ~2 min) · `services/hours/tests` · `services/creao/test_creao_client.py` · `cd web && npx tsc --noEmit`.
- Stage check: Moscone Center → City Hall, day 4, minute 1410 should score 77 vs 57. Re-check after hours-evidence changes and re-run `scripts/export_demo.py`.
- Runtime files (`data/cache/hours_live.json`, new `data/cache/norms/*`, `data/*.db`) are git-ignored; check `git status` after running things anyway.
