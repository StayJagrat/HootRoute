"""Scoot McRoute's preference ranking. The engine's score is never changed; preferences only choose among the engine's own
candidate routes (fastest, balanced, HootRoute) with a deterministic rule, and the reason quotes the engine's numbers."""
from __future__ import annotations

from pydantic import BaseModel, Field

MAX_EXTRA = 1.25        # same walking-time ceiling the engine uses for its recommendation


class Preferences(BaseModel):
    fewerTurns: bool = False
    preferOpenPlaces: bool = False
    preferMainRoads: bool = False
    fastest: bool = False
    lowDistraction: bool = False          # a guidance setting (fewer voice prompts); it does not pick a route
    notes: str = Field("", max_length=200)


def choose_option(options: list[dict], prefs: Preferences | dict | None) -> dict | None:
    """{optionId, reason, rule} or None when there is nothing to choose between or no route preference is set."""
    if prefs is None or not options: return None
    options = [o for o in options if o.get("meetsLimits", True)]
    if not options: return None
    p = prefs if isinstance(prefs, Preferences) else Preferences(**prefs)
    if not (p.fewerTurns or p.preferOpenPlaces or p.preferMainRoads or p.fastest): return None
    fast = next((o for o in options if o["id"] == "fast"), options[0])
    if p.fastest:
        pick = min(options, key=lambda o: (o["stats"]["minutes"], -o["stats"]["score"]))
        return {"optionId": pick["id"], "rule": "fastest", "reason": f"You asked for the fastest walk: {pick['label']} takes {pick['stats']['minutes']} min."}
    ok = [o for o in options if o["stats"]["minutes"] <= fast["stats"]["minutes"] * MAX_EXTRA] or options
    key, said = [], []
    if p.fewerTurns: key.append(lambda o: -o.get("turnsPerKm", 0)); said.append("fewest turns")
    if p.preferMainRoads: key.append(lambda o: o.get("mainPct", 0)); said.append("most main-road walking")
    if p.preferOpenPlaces: key.append(lambda o: o.get("placesOpen", 0)); said.append("most places listed open")
    key.append(lambda o: o["stats"]["score"])
    pick = max(ok, key=lambda o: tuple(k(o) for k in key))
    facts = []
    if p.fewerTurns: facts.append(f"{pick.get('turnsPerKm')} turns per km")
    if p.preferMainRoads: facts.append(f"{pick.get('mainPct')}% on main roads")
    if p.preferOpenPlaces: facts.append(f"{pick.get('placesOpen')} places listed open when you pass")
    facts.append(f"score {pick['stats']['score']}, {pick['stats']['minutes']} min")
    return {"optionId": pick["id"], "rule": " > ".join(said), "reason": f"{pick['label']} has the {', '.join(said)} among routes within {round((MAX_EXTRA - 1) * 100)}% of the fastest time: " + ", ".join(facts) + "."}
