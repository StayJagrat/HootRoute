![tag:innovationlab](https://img.shields.io/badge/innovationlab-3D8BD3)
![tag:hackathon](https://img.shields.io/badge/hackathon-5F43F1)

# Streetwise Scout

Smart walking navigation for San Francisco, in chat. Tell Scout where you are walking and when; it scores the **fastest** route against the **Streetwise** route *at the minute you pass each block* (open places, empty stretches between open places, help points, street lighting, BART running, turns) using a deterministic engine. The score is plain math; agents never change it.

## Try it
- `Walk me from Powell BART to Civic Center at 11:40pm`
- `from Union Square to Ferry Building friday 10pm`
- then `start walk` (check-ins; my rescuer writes a handoff packet if you stop replying, and never contacts emergency services), `ok`, `stop walk`
- `report broken light near Civic Center BART` (drafts a 311 report, never submits it)
- `audit` (data completeness from the night auditor)

## What you get back
A table of both routes (score 0-100, minutes, longest empty stretch, open places, lit street), a one-line reason, and, when a **shop agent** confirms its place is open late, the re-scored result and which shop confirmed it.

## Multi-agent
Scout talks to: place agents (simulated shops) via `HoursQuery`/`HoursReply`, `watcher`, `rescuer`, `reporter`, `night_auditor`. Shop agents in the demo are **SIMULATED**.

Speaks the Agent Chat Protocol. Covers central San Francisco only (Embarcadero to Civic Center, Mission St to Broadway).
