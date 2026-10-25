# Instructions for coding agents (Codex and Claude Code)

**Codex is in charge while Claude Code is at its usage limit.** Claude resumes after the reset. Read `docs/HANDOFF.md` first (decisions, state, ordered pieces), and add a line to its Log when a piece is done.

## Repo and branches
- Trunk is `main` on `StayJagrat/StreetWise`. One branch per piece, named plainly after the piece (`gateway`, `live-mode`, `hills`), with no `feat/` prefix. Small PRs into `main`, rebase before opening, merge as soon as it runs.
- Local branch `backend-import` holds our backend, still uncommitted. Start Piece 1 there.
- Do not push or commit unless the user asks.

## Design
- **The only design is Abhishek's Figma build in `streetwise-web/`.** Use `src/styles/tokens.css`, the mascots in `public/mascots/`, and his components and screens.
- Do not use `apps/web`, `docs/BRAND.md`, `docs/brand-sheet.html`, the amber "Lamp" palette, or placeholder avatars. Do not invent new visual styles; ask Abhishek for new elements.
- Keep it uncluttered. If a screen feels busy, remove something.

## Product rules
- Four agents: Head (Claude), Guide, Checker, Rescuer. The score is deterministic Python in `services/engine`. No model in the score. Models explain, plan and parse.
- Crime is not an input. Say "conditions, not a safety rating". Never write "safe", "unsafe", "dangerous" or "sketchy".
- Nothing calls 911 and nothing is submitted to the city. Demo shops are labelled simulated.
- Say when data is missing.

## Secrets
Keys live in the git-ignored `.env`. Never print, log, commit or paste them. Do not `source` the file into a shell where a malformed line could echo values.

## Run
See the "Run it locally" section of `docs/HANDOFF.md`.
