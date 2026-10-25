# HootRoute: Devpost submission draft

> Paste each section into the matching Devpost field. Lines marked **TODO** need a person before submitting.
> Every number here comes from the engine or from a run we recorded on Oct 24–25, 2026. Don't round them up.

---

## Project name
HootRoute

## Tagline (≤ 60 chars)
Your night shift has a wingman.

## Elevator pitch (≤ 200 chars)
Agentic navigation for the walk after dark. HootRoute compares routes by what's listed open, lit and running when you pass each block, checks what it doesn't know, and replans when the plan changes.

---

## Inspiration
A shift ends at 11:30 PM. The class lets out at midnight. The commute isn't over yet.

Map apps optimise for the fastest route, and late at night that's often the emptiest one. The café that lit up the corner at 6 PM is shut, and the map doesn't know. So the cook, the nurse, the cleaner, or the student leaving the library texts a friend "home?" and hopes.

We wanted to build something for the people who make the city run after dark: late-shift hospitality, healthcare, retail and cleaning workers, and students on late schedules. We gave ourselves one hard rule. **Describe conditions, never rate safety.**

## What it does
You tell HootRoute where you're going, when you're leaving, and what matters to you. A crew of four agents takes it from there:

- **Professor Hoot** (Claude) reads the request in plain words, pulls out your preferences, picks the tools, and runs independent lookups in parallel. It explains every trade-off using only numbers the tools returned, and it **asks before spending money** on an investigation.
- **Scoot McRoute** (deterministic Python engine) generates candidate routes across San Francisco and scores each one at **the minute you'll pass every block**. It counts listed-open places, gaps between them, mapped lighting, main roads, whether transit is running, and turns. It also re-plans around anything you report.
- **Sherlock Hoots** (Apify) finds places on your route whose opening hours are unknown. With your approval, it checks their published listings live. Each result keeps its source, retrieval time and Apify run ID, and the route is re-scored. If nothing changed, Hoot says so.
- **Wingman Wally** (walk rooms) follows your journey with turn-by-turn guidance. If something's blocked, you tap **Report a problem**, and Wally and Hoot come back with alternatives, but **your route never changes until you choose**. You can share a live link with someone you trust and stop sharing at any time; the old link stops working immediately.

Each answer arrives with a trace showing which agent ran which tool, why it ran, how long it took, and what it returned.

**Example: Moscone Center → City Hall, Friday 11:30 PM.** The HootRoute route scores **77 vs 57** for the fastest route. Its longest stretch with nothing listed open is **390 m instead of 560 m**, for about **+1.1 minutes** of walking.

## How we built it
- **Engine (Python, NetworkX, NumPy).** A cached San Francisco OpenStreetMap graph: **139,515 street segments** and **8,907 mapped places**, SF 311 streetlight history, the BART GTFS schedule and SFMTA temporary street closures.
  - Routes are sampled every **10 m**.
  - Opening hours are evaluated at each point's arrival minute.
  - Each walk is compared with typical walks in its own 2 km cell, so one quiet neighbourhood can't skew the scale.
  - No crime data and no model go into the score.
- **Professor Hoot.** Claude tool use (`claude-sonnet-5-5`) with typed tools: `find_place`, `plan_routes`, `rank_by_preferences`, `inspect_route`, `find_route_unknowns`, `propose_hours_check`, `rescore_routes` and `replan_avoiding`. Short explanations use `claude-haiku-5-5`.
  - **Approval is enforced in code, not in the prompt.** Claude can only *propose* a paid check, and the walker's approval runs exactly the approved places.
  - **Numbers are checked.** `numbers_check` compares every number in Claude's prose against the tool results and replaces any answer that states a number no tool produced.
- **Sherlock Hoots.** The Apify Google Maps actor (`compass/crawler-google-places`).
  - Each run is capped at $0.50 and aborted if it runs long.
  - Hours are parsed by a deterministic rules parser and matched by name within 80 m.
  - Checks are reused within 12 hours so the same place isn't paid for twice, and a daily run budget applies.
- **Gateway.** FastAPI with one WebSocket room per journey and SQLite persistence; journeys survive a restart. Each role is checked: walker token, revocable guardian link token, admin token. Rate limits and token redaction in logs.
- **Frontend.** React, TypeScript and Vite PWA, with MapLibre GL over a Geoapify night basemap: 3D buildings, an animated route draw-in, a tilted camera, and custom animated agent avatars.

## Challenges we ran into
- **Keeping the model out of the numbers.** It's tempting to let the LLM "summarise the score". We enforced the opposite in code: Claude decides *what* to calculate, Python calculates it, and a checker rejects prose that invents a number.
- **Time-aware scoring.** "Open" depends on when you get there, so every block is scored at its own arrival minute, not at departure time.
- **Honest uncertainty.** Most small places publish no hours. Those places count as *unknown*, never closed and never risky. They earn no credit in the score, and Sherlock can check them, with your approval.
- **Consequential actions.** A paid API call or a change to someone's active route is a decision the person makes, not the agent. We built explicit approval and choice steps into the protocol.

## Accomplishments that we're proud of
- **A real end-to-end agent loop.** In one recorded run, Claude resolved both places in parallel, planned and scored the routes, applied "fewer turns", inspected the route, found 4 places with unknown hours and **asked to check them**. After approval, Apify run `egA3lxGAjX3j0cuIz` checked 4 listings in 39.7 s for **$0.016**. None of the four is open at 11:30 PM, so the score stayed at 77 and Hoot said exactly that.
- **Mission Recovery.** Report construction mid-walk and get re-scored alternatives that avoid it, from where you are, with a plain explanation. Switching is one tap; nothing switches on its own.
- **Privacy by default.** Sharing is opt-in, link-based and revocable, and GPS traces are deleted after the walk. Nothing is texted or called, and HootRoute never contacts emergency services. A Call 911 button is there for a person to press.
- **21 end-to-end gateway tests**, covering the approval gate, guardian revocation, the numbers check (with a scripted Claude), evidence provenance, recovery and the security defaults.

## What we learned
- Agents are most trustworthy when their power is bounded by the protocol rather than by the prompt.
- Showing *why* each tool ran (the trace) builds more trust than a confident paragraph.
- "Unknown" is a first-class answer. Saying it plainly beats guessing.

## What's next
- Pilots with a hospital and a hotel workers' union, plus campus late-night programmes.
- Live transit arrivals (511.org) and event let-out times, each added only when documented and tested.
- Shopkeeper accounts so local businesses can confirm tonight's hours themselves.
- More cities.

## Built with
`python` `fastapi` `networkx` `numpy` `sqlite` `websockets` `claude` `anthropic-api` `apify` `openstreetmap` `sf-311` `bart-gtfs` `maplibre-gl` `geoapify` `react` `typescript` `vite` `pwa`
**TODO:** add `fetch-ai` `uagents` `cartesia` only if they're shown working in the demo.

## Try it out
- GitHub: https://github.com/StayJagrat/HootRoute
- **TODO:** live demo URL (only a deploy with `HOOTROUTE_ENV=production`; see `docs/RELEASE.md`)
- **TODO:** video link

---

## Sponsor tracks (tick only what's true at submission time)

| Track | What to claim | Status |
|---|---|---|
| **Anthropic: Claude for Public Benefit** | Claude orchestrates real tools for a named community (late-shift workers and students walking after dark). Tool selection, parallel lookups, an approval gate, numbers verified against tools, and recovery coordination. Real run recorded. | ✅ Ready. **TODO:** confirm the rubric at the booth |
| **Apify** | An Actor run for missing-information retrieval, consumed by the app: run id, source URL and timestamp on every result, and re-scoring. Run `egA3lxGAjX3j0cuIz`. | ✅ Ready. **TODO:** screenshot the Apify console run |
| **Fetch.ai** | `head_chat.py` speaks the Agent Chat Protocol, with approve/skip; the four agents run as uAgents. | ❌ **Do not claim yet.** Needs seeds, the Agentverse mailbox, a verified ASI:One conversation, agent addresses in the README, and registration |
| **CREAO** | Hours Detective client exists. | ❌ **Do not claim.** Never run; no agent ID or share link |
| **Figma** | — | ⚠️ The current UI is not the Figma build. Only claim with an honest stage log |
| **People-First / Microsoft social impact** | Consent-based sharing, unknown shown as unknown, no crime data, human-in-the-loop decisions | ✅ Opt in on Devpost |

---

## 3-minute video script

| Time | On screen | Say |
|---|---|---|
| 0:00–0:15 | Landing page, orbiting night map | "A shift ends at 11:30 PM. The commute isn't over. HootRoute is a wingman for that walk." |
| 0:15–0:45 | `/plan`: type "My shift ends at 11:30 PM Friday near Moscone Center, walking to City Hall, fewer turns, places open on the way." The crew strip lights up | "Professor Hoot is Claude. It doesn't make up numbers. It hands the work to Scoot, our routing engine, and Sherlock, our investigator." |
| 0:45–1:10 | Routes on the map: 77 vs 57, 390 m vs 560 m | "Every block is scored at the minute you pass it: what's listed open, mapped lighting, transit running. Conditions, not a safety rating." |
| 1:10–1:40 | Sherlock's approval card → **Run check** → results with the Apify run, before and after | "Four places have unknown hours. Checking costs money, so it asks first. Here's the live Apify run, with a source and a time for every result, and an honest 'nothing changed'." |
| 1:40–1:55 | **Agents** tab: the trace | "Every tool call, why it ran, and what it returned." |
| 1:55–2:35 | Start the journey (labelled GPS replay) → **Report a problem → Construction** → recovery options → **Switch** | "Something's blocked. Wally and Hoot find another way from where you are, and nothing changes until you choose." |
| 2:35–2:50 | Sharing off → guardian view: "Sharing was stopped" | "Share a live link with someone you trust, and stop it any time." |
| 2:50–3:00 | Principles strip | "No crime data. No model in the score. Never calls 911 for you. HootRoute." |

Say on camera that the walk uses a labelled GPS replay.

## Known limits (say them before a judge asks)
- Listed hours are listings, not proof a place is staffed at that minute.
- Hours are unknown for most small places. The app shows how many, and Sherlock can check them.
- Lighting is mapped evidence (OSM lamps and SF 311 history), not live light.
- Transit uses the BART schedule, not live arrivals.
- Coverage is San Francisco only.

## Team
**TODO:** names, roles, and anything specific each person built.
