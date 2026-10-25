"""Build the PWA route contract (DemoData in web/src/lib/types.ts) from the deterministic Python engine."""
from __future__ import annotations

from bisect import bisect_left, bisect_right
from math import hypot

from hootroute_engine.engine import Engine
from hootroute_engine.scoring import Ctx, metrics, score, WALK_SPEED
from hootroute_engine.world import is_open

DAY = 4  # Friday
DEPART = 23 * 60 + 30
ORIGIN = (37.7842, -122.4016)  # Moscone Center: a late shift ends at a hotel or venue here
ORIGIN_NAME = "Moscone Center"
DESTINATION = (37.7793, -122.4193)  # City Hall, by Civic Center BART
DESTINATION_NAME = "City Hall"
SESSION = "_demo_data_export"


def _cumulative(engine: Engine, coords: list[list[float]]) -> list[float]:
    points = [engine.W.proj.xy(lat, lon) for lon, lat in coords]
    out = [0.0]
    for a, b in zip(points, points[1:]):
        out.append(out[-1] + float(hypot(*(b - a))))
    return out


def _point_at(coords: list[list[float]], cumulative: list[float], at: float) -> list[float]:
    i = max(1, min(bisect_left(cumulative, at), len(coords) - 1))
    span = cumulative[i] - cumulative[i - 1]
    t = min(1.0, max(0.0, (at - cumulative[i - 1]) / span)) if span else 0.0
    a, b = coords[i - 1], coords[i]
    return [round(a[0] + (b[0] - a[0]) * t, 7), round(a[1] + (b[1] - a[1]) * t, 7)]


def _slice(coords: list[list[float]], cumulative: list[float], start: float, end: float) -> list[list[float]]:
    middle = [coords[i] for i in range(1, len(coords) - 1) if start < cumulative[i] < end]
    return [_point_at(coords, cumulative, start), *middle, _point_at(coords, cumulative, end)]


def _stats(route: dict) -> dict:
    return {"score": round(route["score"]), "longestEmptyM": route["gap"]["m"], "minutes": route["minutes"]}


def _path_nodes(engine: Engine, route: dict) -> list[int]:
    return [engine.W.nearest_node(lat, lon)[0] for lon, lat in route["coords"]]


def _fixed_route_stats(engine: Engine, route: dict, ctx: Ctx) -> dict:
    m = metrics(engine.W, ctx, _path_nodes(engine, route))
    value, _, _ = score(m, engine.norm(ctx, engine.center_of(route["coords"])))
    return {"score": round(value), "longestEmptyM": round(m["gap_m"]), "minutes": round(m["minutes"], 1)}


def _street_names(route: dict, start: float, end: float) -> str:
    names = []
    for step in route["steps"]:
        if step["at_m"] + step["len_m"] < start or step["at_m"] > end:
            continue
        name = step["street"]
        if name and name != "the path" and name not in names:
            names.append(name)
    if not names:
        return "Walking path"
    return names[0] if len(names) == 1 else f"{names[0]} → {names[-1]}"


def _stretch(engine: Engine, route: dict, on_route: bool, ident: str, day: int = DAY, depart: int = DEPART) -> dict:
    coords = route["coords"]
    cumulative = _cumulative(engine, coords)
    gap = route["gap"]
    start, end = gap["range"] or (0, 0)
    start = max(0.0, min(float(start), cumulative[-1]))
    end = max(start, min(float(end), cumulative[-1]))
    mid = (start + end) / 2
    line = _slice(coords, cumulative, start, end)
    pass_minute = depart + round(mid / WALK_SPEED / 60)
    why = engine.why(SESSION, line[len(line) // 2][1], line[len(line) // 2][0], day, pass_minute)
    lo = max(0, bisect_right(cumulative, start) - 1)
    hi = min(len(coords) - 1, max(lo + 1, bisect_left(cumulative, end)))
    local_ctx = Ctx(day, depart + round(start / WALK_SPEED / 60))
    local = metrics(engine.W, local_ctx, _path_nodes(engine, {"coords": coords[lo:hi + 1]}))
    local_score, _, _ = score(local, engine.norm(local_ctx, engine.center_of(coords)))
    known = local["light_known"]
    confidence = "high" if known >= 0.8 else "medium" if known >= 0.5 else "low"
    lamps = why["lamps"] if why else 0
    outages = why["outages"] if why else 0
    unknown = why["unknown_hours"] if why else 0
    lamp_label = "lamp location" if lamps == 1 else "lamp locations"
    evidence = f"{lamps} {lamp_label} on record nearby; {outages} open streetlight outage reports nearby."
    hours = "No listed open place within 50 m at the arrival minute."
    if unknown:
        hours += f" {unknown} nearby place{'s have' if unknown != 1 else ' has'} no listed hours (unknown, not closed; no credit in the score)."
    return {
        "id": ident,
        "name": _street_names(route, start, end),
        "onRoute": on_route,
        "meters": gap["m"],
        "score": round(local_score),
        "confidence": confidence,
        "line": line,
        "lampEvidence": evidence,
        "lampSource": "OSM street lamps and SF 311 streetlight reports",
        "openPlaces": hours,
        "openSource": "OSM listed hours and matched hours evidence",
        "why": f"This {gap['m']} m stretch has no listed open place or reachable help point on the route. Conditions, not a safety rating.",
    }


def _kind(cat: str) -> str:
    if cat == "pharmacy":
        return "pharmacy"
    if cat in {"convenience", "supermarket", "grocery", "shop"}:
        return "market"
    if cat in {"hotel", "motel", "hostel"}:
        return "hotel"
    return "cafe"


def _close_time(spec: str | None, arrival: int, day: int = DAY) -> str:
    """When a listed-open place closes after you pass it: "HH:MM", "24h", "closed" (listed hours say closed then) or "unknown" (no hours)."""
    if not spec:
        return "unknown"
    if spec == "24/7":
        return "24h"
    if not is_open(spec, (day + arrival // 1440) % 7, arrival % 1440):
        return "closed"
    for minute in range(arrival + 1, arrival + 12 * 60 + 1):
        dd = (day + minute // 1440) % 7
        if not is_open(spec, dd, minute % 1440):
            return f"{minute // 60 % 24:02d}:{minute % 60:02d}"
    return "24h"


def _place(engine: Engine, shop: dict, day: int = DAY, depart: int = DEPART, simulated: bool = True) -> dict:
    arrival = depart + round(shop.get("d", 0) / WALK_SPEED / 60)
    known = engine.W.places[engine.W.place_index[shop["id"]]] if shop["id"] in engine.W.place_index else {}
    return {
        "id": shop["id"], "name": shop["name"] or shop["cat"].replace("_", " ").title(),
        "kind": _kind(shop["cat"]), "lngLat": shop["ll"],
        "openUntil": _close_time(shop["hours"], arrival, day),
        "safeHaven": False, "frontLight": False,
        "simulated": simulated,  # True only in the offline demo export, where a teammate plays the shopkeeper
        "address": None,
        "hoursSource": known.get("hours_source"),
    }


def build_demo_data(engine: Engine) -> dict:
    """Return the fixed offline route with cached, engine-scored shop what-if data."""
    return build_route_data(engine, *DESTINATION, DESTINATION_NAME)


DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _clock(minute: int) -> str:
    h = minute // 60 % 24
    return f"{h % 12 or 12}:{minute % 60:02d} {'AM' if h < 12 else 'PM'}"


def _option(engine: Engine, route: dict, depart: int) -> dict:
    return {"id": route["id"], "label": route["label"], "coords": route["coords"], "steps": route["steps"],
            "stats": _stats(route), "km": route["km"], "placesOpen": route["places_open"], "lightPct": route["light_pct"],
            "points": route["points"], "weights": route["weights"], "turnsPerKm": route["turns_per_km"], "mainPct": route["main_pct"], "avoidsReport": route.get("avoids", True)}


def build_route_data(engine: Engine, lat: float, lon: float, name: str, origin: tuple[float, float] | None = None, origin_name: str | None = None,
                     day: int = DAY, depart: int = DEPART) -> dict:
    """Build the PWA contract for any two points the street graph covers (the whole city), at any departure time."""
    return build_plan(engine, lat, lon, name, origin, origin_name, day, depart)[0]


def initials(name: str) -> str:
    parts = [p for p in name.split() if p]
    return ("".join(p[0] for p in parts[:2]) or "G").upper()


def build_plan(engine: Engine, lat: float, lon: float, name: str, origin: tuple[float, float] | None = None, origin_name: str | None = None,
               day: int = DAY, depart: int = DEPART, walker: str = "Arya", guardian: str = "Maya Chen", session: str = SESSION,
               simulated_shops: bool = True, avoid: list | None = None) -> tuple[dict, dict]:
    """(DemoData for the PWA, the engine's own route dicts keyed 'best' and 'fast' for the agents)."""
    name = name.strip()[:100]
    if not name:
        raise ValueError("Choose a destination.")
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError("Destination coordinates are invalid.")
    origin = origin or ORIGIN
    origin_name = (origin_name or ORIGIN_NAME).strip()[:100]
    destination = (lat, lon)
    with engine.lock:
        origin_node, origin_snap = engine.W.nearest_node(*origin)
        destination_node, snap_distance = engine.W.nearest_node(*destination)
        if origin_snap > 250:
            raise ValueError("The start is outside the mapped part of San Francisco. Pick a point inside the city.")
        destination_snap_m = round(snap_distance)
        if destination_snap_m > 250:
            raise ValueError("The destination is outside the mapped part of San Francisco. Pick a point inside the city.")
        if origin_node == destination_node:
            raise ValueError("Start and destination are the same place. Pick a different destination.")
        engine.clear(session)
        try:
            result = engine.route(session, origin, destination, day, depart, avoid=avoid)
            fastest = next(r for r in result["routes"] if r["id"] == "fast")
            best = next((r for r in result["routes"] if r["id"] == "best"), fastest)
            suggested = engine.suggest_declarations(session, best, day, depart)
            shop = suggested[0] if suggested else None
            named = [p for p in best["shops"] if p["name"] and p["cat"] in {"cafe", "restaurant", "bar", "pub", "pharmacy", "convenience"}]
            selected = []
            for fraction in [0.15, 0.35, 0.6, 0.75]:
                available = [p for p in named if p["id"] not in {s["id"] for s in selected}]
                if available:
                    selected.append(min(available, key=lambda p: abs(p["d"] - fraction * best["km"] * 1000)))
            places = [_place(engine, p, day, depart, simulated_shops) for p in selected]
            what_if = None
            if shop:
                closed = {"id": shop["id"], "name": shop["name"], "cat": shop["cat"], "ll": shop["ll"], "hours": shop["hours"], "d": shop["at"]}
                places.append(_place(engine, closed, day, depart, simulated_shops))      # not open when you pass: closed, or unknown hours
                engine.declare(session, shop["id"], depart + 150, day, depart)
                ctx = engine.ctx(session, day, depart)
                what_if = {
                    "placeId": shop["id"],
                    "passMinute": depart + round(shop["at"] / WALK_SPEED / 60),
                    "statsOpen": {"hootroute": _fixed_route_stats(engine, best, ctx), "shortest": _fixed_route_stats(engine, fastest, ctx)},
                }
                engine.clear(session)
            best_gap = best["gap"]["range"] or [0, best["km"] * 500]
            cumulative = _cumulative(engine, best["coords"])
            stop = _point_at(best["coords"], cumulative, sum(best_gap) / 2)
            debt = engine.darkness_debt(day, depart, near=engine.center_of(best["coords"]), top=3)
            balanced_r = next((r for r in result["routes"] if r["id"] == "balanced"), None)
            data = {
                "scenario": {"label": f"{DAY_NAMES[day]} · {_clock(depart)}", "area": f"{origin_name} → {name}", "segmentsScored": engine.W.stats()["segments"], "departureMinute": depart, "day": day},
                "walker": {"id": "walker", "name": walker},
                "guardian": {"name": guardian, "initials": initials(guardian), "channel": "live link"},
                "start": {"name": origin_name, "lngLat": best["coords"][0]},
                "end": {"name": name, "lngLat": best["coords"][-1]},
                "route": best["coords"],
                "shortest": fastest["coords"],
                "dimStretches": [_stretch(engine, best, True, "hootroute-gap", day, depart), _stretch(engine, fastest, False, "shortest-gap", day, depart)],
                "stopAt": stop,
                "places": places,
                "stats": {"hootroute": _stats(best), "shortest": _stats(fastest), **({"balanced": _stats(balanced_r)} if balanced_r else {})},
                "darknessDebt": [{"street": r["street"], "minutes": r["minutes"]} for r in debt["rows"]],
                "routeSteps": {"hootroute": best["steps"], "shortest": fastest["steps"]},
                "options": [_option(engine, r, depart) for r in result["routes"]],
                "recommended": result["recommended"],
                "whatIf": what_if,
                "dataNote": f"Scores compare this walk with typical walks in the same neighbourhood at the same hour. Places without listed hours earn no credit (unknown, not closed). The destination is snapped to the nearest mapped street, {destination_snap_m} m away. Darkness debt is modeled walker-minutes, not observed foot traffic.",
            }
            routes = {"best": best, "fast": fastest}
            if balanced_r: routes["balanced"] = balanced_r
            return data, routes
        finally:
            engine.clear(session)
