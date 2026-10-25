"""The product name in one place. Set APP_NAME in the repo .env to rename everything the agents say."""
from .config import env

BRAND = env("APP_NAME", "HootRoute")

# Display names for the four agents. Internal ids (message `agent` fields, mascots, uAgents seeds) stay head/guide/checker/rescuer.
PERSONAS = [
    {"id": "head", "persona": "Professor Hoot", "job": "Reads your request, picks the tools, asks before paid checks, explains the trade-offs and coordinates recovery.",
     "runsOn": "Claude tool use (a fixed pipeline when Claude is not configured)"},
    {"id": "guide", "persona": "Scoot McRoute", "job": "Generates candidate routes and scores each one at the minute you pass every block; re-plans around reported obstacles.",
     "runsOn": "Deterministic Python engine over OpenStreetMap, SF 311 and BART data"},
    {"id": "checker", "persona": "Sherlock Hoots", "job": "Finds places on the route with unknown hours, checks their published listings after you approve, and records the source and time.",
     "runsOn": "Apify Google Maps actor + deterministic hours parser"},
    {"id": "rescuer", "persona": "Wingman Wally", "job": "Runs the live journey: obstacle reports, recovery choices, sharing on and off, and the check-in ladder you set up.",
     "runsOn": "Walk rooms and rules; SMS and calls only with your opt-in"},
]
PERSONA = {p["id"]: p["persona"] for p in PERSONAS}
