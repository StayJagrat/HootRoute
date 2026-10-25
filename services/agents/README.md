![tag:innovationlab](https://img.shields.io/badge/innovationlab-3D8BD3)
![tag:hackathon](https://img.shields.io/badge/hackathon-5F43F1)

# Streetwise agents (Fetch.ai uAgents, Cal Hacks 13.0)

Streetwise scores every walking route **at the minute you pass each block** (open places, empty stretches between open places, help points, lamp evidence, BART running, turns) with a deterministic Python engine. These agents sit **above** the engine: they parse a chat request, call the engine, ask shop agents about hours, and look after the walker. **No agent computes or changes a score**; they only call `POST /api/route`, `/api/agents/place/*`, `/api/agents/auditor/run`.

The primary workflow runs entirely inside an ASI:One chat with **`streetwise-scout`**, which implements the Agent Chat Protocol (acks first, `TextContent` in, `TextContent` + `EndSessionContent` out).

```
 ASI:One user ──chat──> scout ──HTTP──> Streetwise engine (FastAPI :8000)
                          │  HoursQuery/HoursReply (send_and_receive)
                          ├──────────> place agents x3 (SIMULATED shops)  ── confirmed? ─> /api/agents/place/declare ─> engine re-scores
                          │  WalkStart / CheckInAck            UserNotice (check-in relayed to chat)
                          ├──────────> watcher ──RescueTrigger──> rescuer (writes handoff file, contacts NOBODY)
                          │  ReportRequest / ReportDraft
                          ├──────────> reporter (writes DRAFT 311 text file, submits NOTHING)
                          └──────────> night_auditor (also on a timer: /api/agents/auditor/run)
```

## Agents

| Agent | Role | Port | Seed env var | Address |
|---|---|---|---|---|
| `streetwise-scout` | Chat front door (ASI:One). Parses request, routes, asks shop agents, replies | 8001 | `SCOUT_SEED` | run `python print_addresses.py` |
| `streetwise-place-chicos-pizza` | **Simulated** shop agent (`n4637773271`) | 8011 | `PLACE_AGENT_1_SEED` | " |
| `streetwise-place-cafe-ellis` | **Simulated** shop agent (`n4637571919`) | 8012 | `PLACE_AGENT_2_SEED` | " |
| `streetwise-place-kim-huong` | **Simulated** shop agent (`n4637572294`) | 8013 | `PLACE_AGENT_3_SEED` | " |
| `streetwise-watcher` | During a walk: check-ins via scout, escalates on silence | 8002 | `WATCHER_SEED` | " |
| `streetwise-rescuer` | On silence: writes a handoff packet file. Never contacts emergency services | 8003 | `RESCUER_SEED` | " |
| `streetwise-reporter` | Writes a DRAFT 311 report file. Never submits | 8004 | `REPORTER_SEED` | " |
| `streetwise-night-auditor` | Calls `/api/agents/auditor/run` on an interval | 8005 | `NIGHT_AUDITOR_SEED` | " |

Addresses are derived from the seeds (`agent1q...`), so they only exist once you set seeds. `python print_addresses.py --md` prints this table with real addresses; paste it back here and into your submission. **Keep seeds stable**: changing one changes the address and breaks the Agentverse registration. The shop agents are simulated and labelled so in their README and in scout's replies; their ids are real engine place ids from `demo_places.json` (regenerate with `python discover_places.py`).

## Live walks (the PWA)

The same five core agents also run real walks for the PWA. Their logic is `streetwise_agents/` (shared with the gateway's in-process runtime). `live_bureau.py` runs them in one Bureau with a second protocol, `streetwise-walk`: room envelopes from the gateway go to the agent that owns them, and Watcher → Rescuer / Reporter / Scout hand-offs are uAgents messages checked against the sender's address. Set `AGENT_RUNTIME=uagents` and `BRIDGE_SECRET` in the repo `.env`, start `live_bureau.py` instead of `run_all.py` (it also serves the chat protocol and the place agents), then restart the gateway. See `docs/BACKEND.md`.

## Setup

Python **3.12** is required (uAgents does not support 3.14).

```bash
cd /Users/aryabhatt/Documents/GitHub/StreetWise
/opt/homebrew/bin/python3.12 -m venv .venv-agents
.venv-agents/bin/pip install -r services/agents/requirements.txt
cd services/agents
cp .env.example .env            # then fill in the seeds: python -c "import secrets; print(secrets.token_hex(24))"
../../.venv-agents/bin/python print_addresses.py
```

Start the engine (if it is not running): `cd services/api && ../../.venv/bin/uvicorn main:app --port 8000`.

## Run

```bash
../../.venv-agents/bin/python run_all.py                 # all agents in one uagents Bureau (mailbox-capable)
../../.venv-agents/bin/python run_all.py --only scout,place
../../.venv-agents/bin/python run_all.py --multiprocess  # one OS process per agent instead
../../.venv-agents/bin/python scout.py                   # any agent alone (also watcher.py rescuer.py reporter.py night_auditor.py, place_agent.py <place_id>)
```

Optional env: `ASI1_API_KEY` (scout then also lets ASI:One extract origin/destination/time when the deterministic parser fails; works without it), `SCOUT_CARDS=1` (adds an Interactive Card carousel after the text; text-only is the default), `SCOUT_FIXED_SESSION=demo` (plan inside the PWA's `demo` session so its trace panel shows scout's steps), `WATCH_CHECK_EVERY_S`, `WATCH_REPLY_DEADLINE_S`. See `.env.example`.

## Test offline (no Agentverse, no ASI:One)

```bash
../../.venv-agents/bin/python test_local.py
```

Starts a local Bureau with every agent plus a client agent that chats with scout over the real chat protocol, and asserts: parse -> engine route -> shop agents confirm -> `/declare` re-scores -> reply text; check-in -> `ok`; silence -> handoff packet file; 311 draft file; audit; junk input. It never registers anything (`STREETWISE_MODE=local`, throwaway seeds, no-op registration).

## Connect to Agentverse and test in ASI:One (human steps)

Needs an Agentverse account (https://agentverse.ai). Scout is the only agent that **must** be connected; connect the others too if you want them discoverable.

1. Fill `.env` (seeds). Run **`python scout.py`** first (alone) so it prints
   `Agent inspector available at https://agentverse.ai/inspect/?uri=...&address=agent1q...`.
2. Open that link in your browser, sign in to Agentverse, click **Connect**, choose **Mailbox**, then **Finish**. The log changes from "Agent mailbox not found" to a connected mailbox. (Repeat for each other agent: `python watcher.py`, ... or `python place_agent.py <place_id>`.)
3. In Agentverse > **Agents** > **Local Agents** open `streetwise-scout`. Check the Overview shows the README with both badges and that the `AgentChatProtocol` manifest is listed (it is published automatically: `publish_agent_details=True`, `publish_manifest=True`).
4. Stop the single agent, then run `python run_all.py` (or leave `scout.py` running and start the others). Mailboxes stay connected because the addresses come from the seeds.
5. In Agentverse click **Chat with Agent** on scout and send `Walk me from Powell BART to Civic Center at 11:40pm Friday`. This proves the chat protocol before involving ASI:One.
6. Open https://asi1.ai, start a chat, and switch on the **Agents** toggle (without it ASI:One will not route to agents). Ask for it by name or intent, e.g. `Use the Streetwise Scout agent: walk me from Powell BART to Civic Center at 11:40pm`, or paste the scout `agent1q...` address. Discovery by search can take a few minutes after the first connect.
7. Hackathon submission: use scout's address, keep the two badges at the top of this README, and say clearly which agents are simulated.

## What was and was not verified here

Verified offline (see `test_local.py`): parser, engine integration, chat-protocol ack/reply shape, `send_and_receive` to shop agents, re-score, watcher/rescuer/reporter/auditor flows, card payload construction against the installed `uagents_core` schema, startup in mailbox mode (prints the inspector link). **Not verified** (needs your account): the actual Agentverse mailbox connection, ASI:One discovery/routing, how ASI:One renders markdown tables and Interactive Cards, proactive check-in messages appearing in an ASI:One chat, and the optional ASI:One (`asi1`) parsing call.
