![tag:innovationlab](https://img.shields.io/badge/innovationlab-3D8BD3)
![tag:hackathon](https://img.shields.io/badge/hackathon-5F43F1)

# HootRoute agents (Fetch.ai uAgents, Cal Hacks 13.0)

Four agents. The **Head** is the public one: it speaks the Agent Chat Protocol, so the whole primary workflow runs inside an ASI:One conversation. The **Guide**, **Checker** and **Rescuer** run live walks; every hand-off between them is a uAgents message checked against the sender's address.

| Agent | Role | Seed env | Address |
|---|---|---|---|
| `hootroute-head` | ASI:One front door. Claude reads the request, delegates to the Guide and Checker, explains, writes the walk report and the overnight audit | `HEAD_SEED` | `python print_addresses.py` |
| `hootroute-guide` | Plans and scores routes with the deterministic engine; re-plans off route | `GUIDE_SEED` | |
| `hootroute-checker` | Inspects the route before you leave (closures, empty stretches, lamp reports, lighting, transit), checks listed hours live (Apify), checks in when you stop | `CHECKER_SEED` | |
| `hootroute-rescuer` | Escalation ladder: live link + SMS → call → backup contact → Call 911 button for people. Never dials 911 | `RESCUER_SEED` | |

```
ASI:One user ──chat──> hootroute-head ──HTTP──> HootRoute gateway (/api/head/ask, /api/walks)
                                                   │ Claude tool use
                                                   ├─ Guide: find_place, plan_routes, rescore_routes
                                                   └─ Checker: inspect_route, find_route_unknowns, check_listed_hours (Apify)
Live walks (live_bureau.py): Checker ──AgentTell──> Rescuer (no reply / help), Checker → Head (arrived), Checker → Guide (re-plan)
```

## In ASI:One
1. *"My shift ends at 11:30 PM near Moscone Center, walk me to City Hall, I'd like more places open."* → verdict, both routes with scores, the Checker's findings, and the agent activity.
2. *"Check the hours"* → live Apify listing check and re-score, in the same conversation.
3. *"Start my walk"* → a walker link and a guardian link.

## Setup
```bash
python3 -m venv .venv-agents && .venv-agents/bin/pip install -r services/agents/requirements.txt
cd services/agents && cp .env.example .env     # four seeds: python -c "import secrets; print(secrets.token_hex(24))"
../../.venv-agents/bin/python print_addresses.py --md
```
The Head calls the gateway at `ENGINE_URL`; set `PUBLIC_URL` to the HTTPS origin people open (for the links it sends).

## Connect to Agentverse
1. `../../.venv-agents/bin/python head_chat.py` prints an Agent inspector link.
2. Open it, sign in to Agentverse, **Connect → Mailbox → Finish**.
3. In Agentverse open `hootroute-head`, check the README shows both badges, then **Chat with Agent**.
4. In asi1.ai turn on the **Agents** toggle and ask for the walk.
5. Submit through the Cal Hacks ASI:One Submission Agent with the Head's address.

## Live walks under uAgents
Set `AGENT_RUNTIME=uagents` and `BRIDGE_SECRET` in the repo `.env`, run `live_bureau.py` (it also serves the Head's chat), then restart the gateway. The walk logic is `hootroute_agents/`, the same code the gateway runs in-process, so the two runtimes cannot drift. Tested in `services/api/tests/test_gateway.py::test_full_walk_under_uagents`.
