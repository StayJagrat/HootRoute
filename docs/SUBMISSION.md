# HootRoute: submission kit (Cal Hacks 13.0, due Sun Oct 25, 9:00 AM PT; be at the venue by 8:00 AM)

## Devpost
**Tagline:** Your night shift has a wingman.

**Short description:** HootRoute is a walking companion for San Francisco late-shift workers. Four agents work together: the Head (Claude) understands your request and coordinates; the Guide scores routes by what is listed open, lit and reachable at the minute you pass each block; the Checker checks what we don't know (live listing checks via Apify) and checks in when you stop; the Rescuer alerts your people step by step if you don't answer. Conditions, not a safety rating: no crime data, no model in the score, and it never calls 911.

**Inspiration:** A shift ends at 11:30 PM. The commute isn't over. Map apps give the fastest route; at that hour it is often the emptiest one, and the person walking texts a friend "home?" and hopes.

**What it does:** (1) Ask in plain words. (2) See the fastest route and the HootRoute route with scores, minutes, and the longest stretch with nothing open. (3) The Checker shows where the score comes from and which places have unknown hours; one tap checks their listings live and the route is re-scored, with a before/after. (4) Walk with voice turns. If you stop on an empty stretch, the Checker asks if you're okay. (5) No answer: live link and text to your guardian, then a call, then your backup contact, then a Call 911 button for a person to press. (6) On arrival the Head writes a short report and a draft 311 streetlight note citing real open cases. Nothing is submitted.

**How we built it:** React + Vite PWA (MapLibre, offline SF basemap), FastAPI gateway with one WebSocket room per walk and SQLite, deterministic Python engine over OSM (139,515 street segments), SF 311 streetlight history and the BART schedule, Claude tool use for the Head, Fetch.ai uAgents + Agent Chat Protocol on Agentverse, Apify Google Maps actor, Twilio, Cartesia Sonic.

**Challenges:** keeping the model out of the numbers; scoring each block at its arrival minute; being honest about missing data (unknown hours stay unknown).

**What's next:** shift-worker pilots with a hospital and a hotel union; more cities; shopkeeper accounts.

**Stage numbers (Fri 11:30 PM, Moscone Center → City Hall):** HootRoute 77 vs fastest 57, longest stretch with nothing open 390 m vs 560 m, +1.1 min. Re-check after any hours change: `.venv/bin/python scripts/export_demo.py`.

## 3:00 demo script (same video works for Fetch.ai's 3–5 min minimum and Figma's 3 min maximum: make it exactly 3:00)
| Time | Show | Say |
|---|---|---|
| 0:00–0:20 | Teammate leaving work at night | "A shift ends at 11:30. The commute isn't over." |
| 0:20–0:50 | `/plan`: type the request to the Head; the answer and agent activity appear | "The Head is Claude. It doesn't make up numbers; it hands the work to the Guide and the Checker." |
| 0:50–1:20 | Checker card: score breakdown, unknown places, **Check listed hours · live** → before/after | "We don't just show stale data. We check it, and say when nothing changed." |
| 1:20–2:05 | Control room + guardian phone: stop on the empty stretch, "You stopped. All good?", no answer, guardian alert, ladder steps | "Your people first, one step at a time. It never dials 911; a person does." |
| 2:05–2:30 | ASI:One chat: same request, "check the hours", "start my walk" | "The whole flow also runs inside ASI:One on Fetch.ai." |
| 2:30–3:00 | Arrival report + architecture + rules | "Conditions, not a safety rating. Every number comes from the engine." |

## Track checklist (things only a human can do are marked YOU)
- **Fetch.ai** — YOU: Agentverse + ASI:One accounts (code `CALHACKS26CALHACKS26AV`). Set the four seeds in `services/agents/.env`, run `python head_chat.py` with the gateway on a public URL (`ENGINE_URL` / `PUBLIC_URL`), open the inspector link → Connect → Mailbox. Paste `python print_addresses.py --md` into README. Register through the ASI:One Submission Agent. Record the in-chat flow.
- **Anthropic** — confirm the rubric at the booth; README section is written.
- **Apify** — put `APIFY_TOKEN` in `.env`, run one live check on the stage route on your laptop, screenshot the before/after and the Apify console run.
- **Cartesia** — YOU: key from play.cartesia.ai (code `CARTESIACALHACKS`) → `CARTESIA_API_KEY` in `.env`. Prepare the separate 2-minute demo-first pitch.
- **Twilio** — YOU: trial account, verify your phone and a teammate's, put `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER` in `.env`. Set the guardian and backup phones in `/setup`.
- **Figma** — YOU: .edu-verified account, files shared with "Anyone", a **Figma Slides deck**, and the stage log below.
- **People-First, Microsoft, Meta, Commit Fellowship, Vultr** — opt in on Devpost; nothing extra to build.

## Figma stage log (≤200 words per stage; fill in the real tools, times and ratings)
| Stage | Figma tools and why | Time | Worked (1–5) | How it fed the build |
|---|---|---|---|---|
| Ideation | | | | |
| Prototyping | | | | |
| Handoff | Variables → `src/styles/tokens.css`; mascot component set → `public/mascots/` | | | |
| Code generation | | | | |
Include dead ends honestly; judges score the log on its own ($2,000 Best Stage Log).

## Known limits (say them before a judge asks)
Listed hours are listings, not proof a place is staffed. Hours are unknown for most small places (the Checker shows how many). Lighting is mapped evidence, not live light. The stage walk is a labelled GPS replay. Speech input uses the browser's recognizer.
