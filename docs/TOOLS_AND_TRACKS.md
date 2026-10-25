# Streetwise: tools and tracks (decided list)

Cal Hacks 13.0. Deadline: Sunday Oct 25, 2026, 9:00 AM PT. Prize amounts come from the [Cal Hacks 13.0 Devpost](https://cal-hacks-13-0.devpost.com/) page.

Status key: **LOCKED** we build with it. **OPTIONAL** only after the core works. **VERIFY** a rule or fact we have not confirmed. **DROPPED** not using it.

## 1. What Streetwise is

Smart walking navigation. Every block is scored by what is open, lit and reachable at the minute you pass it, using a published formula. Agents keep the score's inputs true and act on it. The score is plain math; no model produces it.

## 2. Tools

### Client (PWA)

| Tool | Status | Used for | Notes |
| --- | --- | --- | --- |
| React 18, TypeScript, Vite 5 | LOCKED | The installable app | One codebase, four screens: walker, guardian, shopkeeper, control room |
| MapLibre GL JS | LOCKED | Map, route glow, heat layer, place markers | |
| Carto Dark Matter basemap | LOCKED, VERIFY terms | Dark basemap, no key | Fallback: a self-hosted style |
| Zustand, Framer Motion | LOCKED | State, sheet and card animation | |
| vite-plugin-pwa (Workbox) | LOCKED | Install to home screen, offline cache | iOS web push is partial: VERIFY before relying on it |
| Google Fonts: Bricolage Grotesque, IBM Plex Sans, IBM Plex Mono | LOCKED | Brand type | See `docs/BRAND.md` |
| Figma | LOCKED | Design system, prototype | Variables map one-to-one to `src/design/tokens.css` |

### Backend and engine

| Tool | Status | Used for | Notes |
| --- | --- | --- | --- |
| Python, FastAPI, Uvicorn, Pydantic | LOCKED | API and WebSocket agent trace | Engine runs on Python 3.14 here. Pin 3.12 if uAgents needs it (unverified) |
| NetworkX, NumPy | LOCKED | Street graph, routing, scoring | `services/engine` |
| WebSockets | LOCKED | Live agent trace in the app | |

### Data

| Source | Status | Used for | Notes |
| --- | --- | --- | --- |
| OpenStreetMap via Overpass | LOCKED | Street graph, places, listed hours, lamps | Overpass is slow and flaky. Everything is cached in `data/cache` and committed |
| SF 311 streetlight cases (data.sf.gov `vw6y-z8j6`) | LOCKED | Lamp evidence, open outage reports | 27% of cases have no coordinates, only an address |
| BART schedule (GTFS) | LOCKED | "Transit running at your time" | |
| Muni schedule | DROPPED | | Feed was not reachable. Muni stops from OSM count at partial weight |
| SFPD incident reports | DROPPED as an input | Research only | The score does not use crime. See the finding in `research/` |
| Mapillary or Street View imagery | OPTIONAL | Explaining a block with a photo | Never feeds the score. Google restricts caching Street View imagery |

### Agents and AI

| Tool | Status | Used for | Notes |
| --- | --- | --- | --- |
| Fetch.ai uAgents, Agentverse, ASI:One, Agent Chat Protocol | LOCKED | Scout, Watcher, Rescuer, Reporter, Night Auditor and place agents | Python 3.12 pin to be tested |
| Anthropic Claude (Haiku 5.5 `claude-haiku-5-5`, Sonnet 5.5 `claude-sonnet-5-5`) | LOCKED | Understanding "get me home via an open pharmacy", writing plain-language explanations, the Watcher's context judgment | Never computes or changes the score |
| Elastic Serverless, Agent Builder, ES\|QL tools, MCP | LOCKED | Shared city memory the agents read and write | ES\|QL tool parameter syntax: VERIFY at the booth |
| Apify: Google Maps actor, our Actor `street-pulse` | LOCKED (Actor publish is a stretch) | Fills the missing opening hours (56% of places have none listed) | Scraping Google Maps may breach its terms: demo corridor only, OSM as fallback |
| Cartesia (Ink, Sonic) | OPTIONAL | Spoken narration | Only if the core is done. Voice is not required for the product |
| Twilio SMS | OPTIONAL | Alert a verified teammate as a backup to the guardian page | Trial accounts text verified numbers only |
| Moss | OPTIONAL | Retrieval of place facts during a voice turn | Only with a spare hour |
| Convex | DROPPED | | Would add a second backend language |
| Creao | OPTIONAL | Night Auditor as a scheduled Agent App | Rules not public: VERIFY |

### Infrastructure

| Tool | Status | Used for |
| --- | --- | --- |
| GitHub `StayJagrat/StreetWise` | LOCKED | Repo (public before submission, no keys) |
| Vultr VPS with Caddy | LOCKED for the demo | HTTPS hosting, also the MLH Vultr prize |
| Cloudflare Tunnel or ngrok | LOCKED for dev | HTTPS to a phone |
| GoDaddy Registry domain | OPTIONAL | MLH domain prize |

## 3. Tracks

### Build for these

| Track | Prize (listed) | What we build for it | Must have before submitting |
| --- | --- | --- | --- |
| **Fetch.ai** Best Use | $1,500 / $1,000 / $500 | Five uAgents plus place agents on Agentverse. The main flow also works in ASI:One chat | Agent registered, Chat Protocol on, reachable in ASI:One, real tool use or agent-to-agent messages, public repo with run steps, README with each agent's name and address and the Innovation Lab badges, 3 to 5 min video. Rules taken from the MHacks 2026 hackpack: **VERIFY** the Cal Hacks version |
| **Apify** (five places plus Best Actor) | $2,000 / $1,000 / $800 / $400 / $400, Best Actor $400 | Google Maps actor reads hours and popular times into the places index. Our Actor `street-pulse` returns a segment's aliveness at an hour | Actor runs shown in the demo, published Actor with a clear README |
| **Elastic** Agent Builder on Serverless | 1st $1,200 + Meta Quest 3S, 2nd $1,436 + Bose QuietComfort | Elastic holds places, segments, lamp evidence and the agent log. An Agent Builder agent with tools (`segments_near`, `open_places_now`, `stale_reports`, `top_darkness_debt`) is exposed over MCP | Data in Serverless, custom tools, MCP exposure, a short note on how Elastic is used |
| **Cal Hacks Best People-First Social Impact** | Apple Watch SE 3 per member | Night walkers, students, shift workers. Scores come from street conditions, not neighborhoods, and the data shows why crime counts mislead | The fairness finding on one slide, the guardian page, explained scores |
| **Figma** (five prizes) | $1,000 each: Best Use Case of Figma, Best Use Case of Figma Agent, Most Creative Use Case of Figma Agent, Best Design, Most Creative | One variable set drives every screen. A working prototype of the three flows | **VERIFY** what each prize judges and what counts as using the Figma Agent |

### Come from demo quality (no extra build)

Cal Hacks Overall (1st $3,600 plus a MacBook Air or Framework per member), Most Technically Advanced Hack, Most Creative Project, Hacker's Choice. Judging criteria: Application, Intentionality, Functionality, Creativity, Technical Complexity. A live or recorded demo is required, plus a video on Devpost.

### Cheap extras

| Track | Prize | What it takes |
| --- | --- | --- |
| MLH Vultr | M5Stack Tab5 | Host the demo on Vultr. **VERIFY** the rule |
| MLH GoDaddy Registry Best Domain | Gift card | Register the project domain. **VERIFY** which TLDs count |
| MLH Commit Fellowship | Interview and founder sprint | Opt in only if the team wants to keep building; needs a supplemental form |

### Verify, then decide

| Track | Why unsure |
| --- | --- |
| Anthropic | Not on the Devpost list. A teammate's notes say a track exists on the Hive prizes page (login needed). Claude is already core to the product, so it costs nothing to enter once the rubric is known |
| Cartesia ($1,516) | Only worth it if we keep spoken narration |
| Microsoft Built for the Real World ($3,800) | Requirements not visible |
| Creao ($8,760 listed value per track) | Needs real integration time |
| Moss ($996) | Fits retrieval, small prize, new SDK |

### Dropped

Convex, Hyphenate, Visa, Capital One, CRS, Coinbase, Armadin, Factory, Bitdeer, Notability, SpaceXSI, and the MLH Gemini, Solana, Snowflake and Tiger Data tracks unless we end up using those tools.

## 4. How the tools show up in the product

| Feature | Tools |
| --- | --- |
| Score a route at the minute you pass each block | Engine (NetworkX, NumPy), OSM, SF 311, BART |
| "Get me home, past an open pharmacy" | Claude turns the sentence into constraints; the engine does the routing |
| Shop declares "open until 1 AM" and the route changes live | Place agent (uAgents), engine re-score, WebSocket trace |
| Fill missing opening hours | Apify, stored in Elastic |
| Ask "what's open near me?" | Elastic Agent Builder tool over MCP |
| Stop on an empty stretch, check-in, alert | Watcher and Rescuer agents, guardian page |
| Overnight audit and 311 draft | Night Auditor, Reporter, Elastic |

## 5. Decisions the team must confirm now

1. Is voice (Cartesia) in or out? Recommended: out until the core works.
2. Pilot area. Downtown box (about 1.1 by 1.7 km, fully cached and tested) or the bigger central SF area (needs a tiled download that is currently timing out)?
3. Owners. Proposed: Jagrat full-stack and agents, Abhishek Figma and front-end polish, Arya engine, data, Elastic and Apify, the fourth teammate demo and pitch.
4. Who runs the Anthropic and Figma booth checks in the first hour.
