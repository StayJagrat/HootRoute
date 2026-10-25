# Instructions for coding agents (Claude Code, Codex)

Read `README.md`, then `docs/BACKEND.md` (how it fits together) and `docs/SUBMISSION.md` (deadline, tracks, demo).

## Product rules
- Four agents: **Head** (Claude: interprets, delegates, explains, reports), **Guide** (routing), **Checker** (inspection, listing checks, check-ins), **Rescuer** (escalation ladder).
- The score is deterministic Python in `services/engine`. No model produces or changes a number; models explain, plan and parse.
- Crime is not an input and neighbourhoods are never graded. Say "conditions, not a safety rating". Never write "safe", "unsafe", "dangerous" or "sketchy".
- Nothing dials 911 and nothing is submitted to the city. The last rescue rung is a Call 911 button a person presses.
- Unknown is unknown: missing hours or data are shown as missing, never as closed or risky. Demo shops and replays are labelled.

## Design
- One design system: `web/src/styles/tokens.css` (Night and Day), the owl logo in `web/public/brand/`, mascots from `web/scripts/gen-assets.mjs`. No new visual styles without the designer.
- Keep screens uncluttered. If a screen feels busy, remove something.

## Repo
- Trunk is `main` on `StayJagrat/HootRoute`. Small branches named after the piece, small PRs. Do not push or commit unless the user asks.
- Keys live in the git-ignored `.env`. Never print, log, commit or paste them.

## Run and test
`services/api`: `../../.venv/bin/uvicorn main:app --port 8000` · `web`: `npm run dev` · tests: `.venv/bin/python -m pytest services/api/tests -q`.
