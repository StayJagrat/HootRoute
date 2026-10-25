"""Spoken route descriptions for people who navigate by ear (blind and low-vision walkers, or anyone keeping the phone in a
pocket). Deterministic: every number and street comes from the engine's route, so it can be read by Cartesia or by
on-device speech without a model in the loop.

    describe(plan, routes, key)  -> {"overview": str, "directions": [str], "text": str}
"""
from __future__ import annotations

NAMES = {"fast": "the fastest route", "balanced": "the balanced route", "best": "the HootRoute route"}
MODE_VERB = {"walk": "walk", "cycle": "ride", "wheelchair": "journey"}


def _m(meters: float) -> str:
    m = max(10, round(meters / 10) * 10)
    return f"{m / 1000:.1f} kilometres".replace(".0 ", " ") if m >= 1000 else f"{m} metres"


def _places(n: int) -> str:
    return "No place is listed open" if not n else "1 place is listed open" if n == 1 else f"{n} places are listed open"


def _clock(minute: float) -> str:
    x = int(round(minute)) % 1440; h, mm = divmod(x, 60)
    return f"{(h % 12) or 12}{f':{mm:02d}' if mm else ''} {'AM' if h < 12 else 'PM'}"


def _turn(maneuver: str) -> str:
    return {"left": "turn left", "right": "turn right", "slight left": "bear left", "slight right": "bear right",
            "sharp left": "turn sharply left", "sharp right": "turn sharply right", "straight": "continue straight"}.get(maneuver, maneuver)


def overview(plan: dict, routes: dict, recommended: str | None) -> str:
    opts = [o for o in plan.get("options") or [] if o["id"] in routes]
    if not opts: return ""
    mode = MODE_VERB.get(plan.get("travelMode") or "walk", "walk")
    parts = [f"{len(opts)} route option{'s' if len(opts) != 1 else ''} from {plan['start']['name']} to {plan['end']['name']}, leaving {plan['scenario']['label'].replace(' · ', ' at ')}."]
    order = sorted(opts, key=lambda o: (o["id"] != (recommended or "best"), o["stats"]["minutes"]))
    for i, o in enumerate(order, 1):
        st = o["stats"]; r = routes[o["id"]]
        line = (f"Option {i}, {NAMES.get(o['id'], o['label'])}{', recommended' if o['id'] == recommended else ''}: about {round(st['minutes'])} minutes, "
                f"{_m(r['km'] * 1000)}, condition score {st['score']} out of 100. "
                f"{_places(o.get('placesOpen', r.get('places_open', 0)))} as you pass, and the longest stretch with nothing listed open is {_m(st['longestEmptyM'])}.")
        if o.get("turnsPerKm") is not None: line += f" It has about {o['turnsPerKm']} turns per kilometre."
        parts.append(line)
    parts.append(f"Scores describe conditions at the minute you pass each block, not a safety rating. Places with no published hours are unknown, not closed. "
                 f"Say or tap which route you want, and I'll guide you step by step on your {mode}.")
    return " ".join(parts)


def directions(plan: dict, route: dict, depart_minute: int, speed_mps: float | None = None) -> list[str]:
    """Turn-by-turn with the listed-open places woven in at the point you reach them."""
    steps = route.get("steps") or []
    speed = speed_mps or route.get("speedMps") or 1.35
    shops = sorted(route.get("shops") or [], key=lambda s: s.get("d", 0))
    out: list[str] = []
    if steps:
        out.append(f"Start on {steps[0]['street']}" + (f" and go about {_m(steps[0]['len_m'])}." if steps[0].get("len_m") else "."))
    si = 0
    for st in steps[1:]:
        while si < len(shops) and shops[si].get("d", 0) < st["at_m"]:
            s = shops[si]; si += 1
            if s.get("name"): out.append(f"On your way, {s['name']}, a {str(s.get('cat', 'place')).replace('_', ' ')}, is listed open, about {_m(s['d'])} into the route.")
        street = "the path" if st["street"] == "the path" else st["street"]
        out.append(f"After {_m(st['at_m'])} in total, {_turn(st['maneuver'])} onto {street}" + (f", then continue about {_m(st['len_m'])}." if st.get("len_m") else "."))
    for s in shops[si:]:
        if s.get("name"): out.append(f"Near the end, {s['name']} is listed open, about {_m(s['d'])} into the route.")
    total_m = route["km"] * 1000
    arrive = depart_minute + total_m / speed / 60
    out.append(f"You arrive at {plan['end']['name']} after about {_m(total_m)}, around {_clock(arrive)} if you leave on time.")
    return out


def describe(plan: dict, routes: dict, key: str, depart_minute: int) -> dict:
    key = key if key in routes else "best"
    ov = overview(plan, routes, plan.get("recommended"))
    dirs = directions(plan, routes[key], depart_minute)
    intro = f"Directions for {NAMES.get(key, 'this route')}."
    return {"route": key, "overview": ov, "directions": dirs, "text": " ".join([ov, intro, *dirs]).strip()}
