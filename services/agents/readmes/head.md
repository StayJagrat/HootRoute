![tag:innovationlab](https://img.shields.io/badge/innovationlab-3D8BD3)
![tag:hackathon](https://img.shields.io/badge/hackathon-5F43F1)

# HootRoute Head

A walking companion for San Francisco late-shift workers (hospitality, service and healthcare staff) walking home after dark. Chat with me in ASI:One:

- *"My shift ends at 11:30 PM near Moscone Center, walk me to City Hall, I would like more places open."*
- *"Check the hours"*: a live Apify check of listings for places on your route with unknown hours, then a re-score.
- *"Start my walk"*: a walker link and a guardian link.

I use Claude to understand you and coordinate three agents: the **Guide** (deterministic route scoring at the minute you pass each block: listed-open places, gaps, help points, mapped lighting, transit), the **Checker** (unknown hours, live listing checks, check-ins), and the **Rescuer** (escalation ladder to your trusted contacts). Every number comes from the engine, not the model.

Conditions, not a safety rating. No crime data. HootRoute never calls 911.
