"""Checker's pre-walk inspection: walk the chosen route on the map before you do, and say "Good to go" or what to know.

Each item has a level (ok / note / warn), a plain title, a detail and its source. Everything comes from cached public data
and the deterministic engine. Nothing here is a safety rating: no crime data, and missing data is reported as missing.

Sources: the engine's route metrics (listed-open places, gaps, mapped lighting), open SF 311 streetlight reports,
the BART schedule, and SFMTA temporary street closures (data/cache/closures.json from scripts/fetch_closures.py).
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

from .config import env

ROOT = Path(__file__).resolve().parents[3]
CLOSURES = Path(env("CLOSURES_FILE", str(ROOT / "data" / "cache" / "closures.json")))
SF = ZoneInfo("America/Los_Angeles")
WALK = 1.35


def clock(minute: int) -> str:
    m = int(minute) % 1440; h, mm = divmod(m, 60)
    return f"{(h % 12) or 12}:{mm:02d} {'AM' if h < 12 else 'PM'}"


def walk_date(day: int) -> date:
    """The next calendar date (today included) that falls on weekday `day` in San Francisco."""
    today = datetime.now(SF).date(); return today + timedelta(days=(day - today.weekday()) % 7)


def densify(W, coords: list, step: float = 10.0) -> tuple[np.ndarray, np.ndarray]:
    pts = np.array([W.proj.xy(lat, lon) for lon, lat in coords]); out, along = [], []; acc = 0.0
    for i in range(len(pts) - 1):
        L = float(np.hypot(*(pts[i + 1] - pts[i]))); n = max(1, int(L // step))
        for j in range(n): out.append(pts[i] + (pts[i + 1] - pts[i]) * (j / n)); along.append(acc + L * j / n)
        acc += L
    out.append(pts[-1]); along.append(acc)
    return np.array(out), np.array(along)


@lru_cache(maxsize=1)
def _closures(mtime: float) -> dict:
    return json.loads(CLOSURES.read_text(encoding="utf-8"))


def closures_on(W, P: np.ndarray, A: np.ndarray, when: date) -> tuple[list[dict] | None, str | None]:
    """Closures active on `when` whose geometry comes within 20 m of the route. None when the closures file is missing."""
    if not CLOSURES.exists(): return None, None
    blob = _closures(CLOSURES.stat().st_mtime); hits = []; day = when.isoformat()
    lo, hi = P.min(0) - 60, P.max(0) + 60
    for c in blob.get("closures", []):
        if not (c.get("start", "") <= day <= c.get("end", "9999")): continue
        for line in c.get("lines", []):
            Q = np.array([W.proj.xy(lat, lon) for lon, lat in line])
            if not len(Q) or (Q[:, 0].max() < lo[0] or Q[:, 0].min() > hi[0] or Q[:, 1].max() < lo[1] or Q[:, 1].min() > hi[1]): continue
            d = np.hypot(P[:, None, 0] - Q[None, :, 0], P[:, None, 1] - Q[None, :, 1]); k = int(d.min(axis=1).argmin())
            if d[k].min() <= 20:
                hits.append({**{x: c.get(x) for x in ("id", "type", "name", "street", "from", "to", "start", "end", "info")}, "atM": round(float(A[k]))}); break
    return sorted(hits, key=lambda h: h["atM"]), blob.get("fetched_at")


def inspect(engine, data: dict, routes: dict, key: str, day: int, minute: int) -> dict:
    W = engine.W; route = routes[key]
    stats = next((o["stats"] for o in data.get("options", []) if o["id"] == key), data["stats"]["hootroute" if key == "best" else "shortest"])
    P, A = densify(W, route["coords"]); items: list[dict] = []; missing: list[str] = []
    arrive = minute + round(stats["minutes"])
    add = lambda level, title, detail, source: items.append({"level": level, "title": title, "detail": detail, "source": source})

    # 1. closures and construction
    hits, fetched = closures_on(W, P, A, walk_date(day))
    if hits is None:
        missing.append("Street closures and construction (SFMTA): not loaded yet. Run scripts/fetch_closures.py.")
    elif hits:
        for h in hits[:3]:
            where = h.get("street") or "a street on the route"
            t = lambda x: " ".join(w.capitalize() if not w[:1].isdigit() else w.lower() for w in str(x).split())
            span = f" between {t(h['from'])} and {t(h['to'])}" if h.get("from") and h.get("to") else ""
            add("warn", f"{(h.get('type') or 'Street closure').capitalize()} on {t(where)}{span}",
                f"{h.get('name') or 'Permitted closure'}, {h['start']} to {h['end']}. About {h['atM']} m into your walk. Sidewalks may still be open; expect detours.",
                f"SFMTA temporary street closures, data as of {fetched or 'unknown'}")
    else:
        date_label = walk_date(day)
        add("ok", "No permitted street closures on the route", f"Checked for {date_label.strftime('%a %b')} {date_label.day}.", f"SFMTA temporary street closures, data as of {fetched or 'unknown'}")

    # 2. the longest stretch with nothing listed open
    gap = stats["longestEmptyM"]; stretch = next((d for d in data.get("dimStretches", []) if d["onRoute"] == (key == "best")), None)
    name = stretch["name"] if stretch else "one stretch"
    if gap >= 300: add("warn", f"{gap} m with nothing listed open", f"On {name}. HootRoute checks in if you stop there.", "OSM listed hours + matched hours evidence, at your arrival minute")
    elif gap >= 150: add("note", f"Longest gap between open places: {gap} m", f"On {name}.", "OSM listed hours + matched hours evidence")
    else: add("ok", "Open places all along the way", f"Never more than {gap} m from a listed-open place or help point.", "OSM listed hours + matched hours evidence")

    # 3. open streetlight reports
    cases = []
    if W.outage_cases:
        for c in W.outage_cases:
            d = np.hypot(P[:, 0] - c["p"][0], P[:, 1] - c["p"][1]); k = int(d.argmin())
            if d[k] <= 30: cases.append({**{x: c[x] for x in ("id", "opened", "details")}, "atM": round(float(A[k]))})
    if cases:
        cases.sort(key=lambda c: c["atM"])
        add("warn" if len(cases) >= 2 else "note", f"{len(cases)} open streetlight report{'s' if len(cases) != 1 else ''} on the route",
            "; ".join(f"#{c['id']} ({c['details']}, opened {c['opened']})" for c in cases[:3]) + ". Reported, not confirmed out tonight.", "SF 311 streetlight cases (open)")
    else:
        add("ok", "No open streetlight reports on the route", "Based on open SF 311 streetlight cases.", "SF 311 streetlight cases (open)")

    # 4. mapped lighting
    lp = route.get("light_pct", 0); known = route.get("light_known_pct", 0)
    if known < 50: missing.append(f"Lighting is mapped for only {known}% of this route.")
    if lp >= 70: add("ok", f"Mapped lighting on {lp}% of the route", "Street lamps on record or streets tagged lit.", "OSM street lamps and lit tags")
    elif lp >= 45: add("note", f"Mapped lighting on {lp}% of the route", "Some stretches have no lamp on record.", "OSM street lamps and lit tags")
    else: add("warn", f"Mapped lighting on only {lp}% of the route", "Many stretches have no lamp on record. Mapped, not measured.", "OSM street lamps and lit tags")

    # 5. unknown hours
    unk = route.get("unknown_hours_nearby") or 0
    if unk: add("note", f"{unk} places on the route publish no hours", "Their hours are unknown, so they earn no credit in the score (unknown, not closed). Ask Sherlock to check their listings.", "OSM places without opening_hours")

    # 6. transit at the destination
    end = W.proj.xy(route["coords"][-1][1], route["coords"][-1][0])
    near = [(float(np.hypot(*(b["p"] - end))), b) for b in W.bart]; near = [x for x in near if x[0] <= 500]
    if near:
        dist, b = min(near, key=lambda x: x[0])
        if W.bart_running(b, day % 7, arrive): add("ok", f"{b['name']} BART is running when you arrive", f"Arrive about {clock(arrive)}.", "BART GTFS schedule (scheduled, not live)")
        else: add("warn", f"No BART service at {b['name']} when you arrive", f"Arrive about {clock(arrive)}. Plan another way home from there.", "BART GTFS schedule (scheduled, not live)")

    warns = [i for i in items if i["level"] == "warn"]
    if route.get("help_access_unknown"):
        missing.append(f"Public entrance access is unverified for {route['help_access_unknown']} nearby help locations; they receive no help-access credit.")
    verdict = "Good to go" if not warns else f"Heads up: {len(warns)} thing{'s' if len(warns) != 1 else ''} to know"
    order = {"warn": 0, "note": 1, "ok": 2}
    return {"verdict": verdict, "good": not warns, "score": stats["score"], "minutes": stats["minutes"], "arrive": clock(arrive), "route": key,
            "items": sorted(items, key=lambda i: order[i["level"]]), "missing": missing, "note": "Conditions, not a safety rating. No crime data is used."}
