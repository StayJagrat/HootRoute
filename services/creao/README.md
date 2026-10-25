# Creao: Hours Detective

Creao's rule: a CREAO agent built on agent.creao.ai must do the core work, and the Devpost README needs the agent ID plus a share link to one of its runs.

Here the agent does the part that is hardest to automate: verifying opening hours for places where Apify and OpenStreetMap have nothing. The app shows such places as "unverified" until the agent answers.

1. Sign up (hackathon link in the Creao starter pack) and ask the booth for the Pro Plus upgrade.
2. Follow `agent_prompt.md` to build and save the agent. Copy its **agent ID**. Create an API key (Settings, API Keys, starts with `capi_`).
3. Put `CREAO_API_KEY=` and `CREAO_AGENT_ID=` in the repo-root `.env`.
4. Try it: `../../.venv/bin/python creao_client.py --limit 3`. Runs take minutes. Start with `--dry-run` to see which places would be sent.
5. Share link: open one finished run, use the share icon, and paste the link in the submission README. If API runs are not shareable, run the agent once by hand in chat and share that run (untested, check early).

Unverified: the exact API paths and response fields (taken from Creao's docs), per-run credit cost, and whether browsing works on API runs.
