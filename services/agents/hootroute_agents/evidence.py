"""Sherlock Hoots' evidence record: what we know about a place's hours, where it came from, and when.

Kinds of hours evidence on a place
- osm_tag        : OpenStreetMap `opening_hours` tag. Community-edited; the date of the last edit is not in our extract.
- listing_batch  : published hours from the overnight Apify Google Maps run (data/cache/hours_evidence.json), with its fetch time.
- listing_live   : published hours from a check the walker approved (data/cache/hours_live.json), with source URL, run id and time.
- shopkeeper     : tonight's declaration on the shop page. Not verified.
- none           : unknown. Unknown hours earn no credit in the score and are never shown as closed or risky.

None of these confirm that a place is staffed at the minute you pass: `confirmedOpenNow` is always false.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone

import numpy as np

from hootroute_engine.scoring import place_open
from hootroute_engine.world import public_entrance
from hootroute_engine.mobility import travel_profile

from .config import env

WALK = 1.35
STALE_DAYS = float(env("EVIDENCE_STALE_DAYS", "30"))
TTL_HOURS = float(env("EVIDENCE_TTL_HOURS", "12"))
STAFFED = "Published hours, not confirmation that the place is staffed when you pass."


def now_iso() -> str: return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_ts(ts: str | None) -> float | None:
    if not ts: return None
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            d = datetime.strptime(ts.replace("+00:00", "+0000"), fmt)
            return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).timestamp()
        except ValueError: continue
    try: return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except ValueError: return None


def is_stale(ts: str | None, days: float = STALE_DAYS) -> bool:
    t = parse_ts(ts); return t is not None and time.time() - t > days * 86400


# ---------------------------------------------------------------------------------------------- results of a listing check
KIND_OF_STATUS = {"hours found": "published_hours", "no hours": "no_published_hours", "closed": "listed_closed", "not found": "not_found", "check failed": "check_failed"}
NOTE_OF_KIND = {
    "published_hours": STAFFED,
    "no_published_hours": "The listing exists but publishes no schedule. Hours stay unknown.",
    "listed_closed": "The listing says the place is closed.",
    "not_found": "No listing matched this name within 80 m. Hours stay unknown.",
    "check_failed": "The check did not finish. Hours stay unknown; nothing was changed.",
}


def from_result(r: dict, run: dict | None, mock: bool, reused: bool = False) -> dict:
    """One listing-check result in the shared Evidence shape (docs/AGENT_API.md)."""
    kind = KIND_OF_STATUS.get(r.get("status"), "check_failed"); url = r.get("source")
    provider = "mock" if mock or (isinstance(url, str) and url.startswith("mock://")) else "apify"
    return {"placeId": r["id"], "name": r.get("name"), "kind": kind, "hours": r.get("hours") if kind in ("published_hours", "listed_closed") else None,
            "source": {"provider": provider, "url": url if isinstance(url, str) and url.startswith("http") else None, "actor": (run or {}).get("actor"),
                       "runId": (run or {}).get("runId") or r.get("runId"), "consoleUrl": (run or {}).get("consoleUrl") or r.get("consoleUrl"), "listingName": r.get("listingName")},
            "retrievedAt": r.get("checkedAt"), "confidence": r.get("confidence"), "stale": is_stale(r.get("checkedAt")), "reused": reused,
            "confirmedOpenNow": False, "note": NOTE_OF_KIND[kind] + (" (Offline test stand-in, not a real listing.)" if provider == "mock" else "")}


def reusable(entry: dict | None, ttl_hours: float = TTL_HOURS) -> bool:
    """An earlier check of this place that is recent enough to reuse instead of paying for a new one."""
    if not entry or entry.get("kind") == "check_failed": return False
    t = parse_ts(entry.get("checked_at")); return t is not None and time.time() - t < ttl_hours * 3600


def result_from_store(pid: str, e: dict) -> dict:
    status = {v: k for k, v in KIND_OF_STATUS.items()}.get(e.get("kind") or "published_hours", "hours found")
    return {"id": pid, "name": e.get("name"), "status": status, "hours": e.get("opening_hours"), "source": e.get("url"), "checkedAt": e.get("checked_at"),
            "confidence": e.get("confidence"), "listingName": e.get("listing_name"), "runId": e.get("run_id"),
            "consoleUrl": f"https://console.apify.com/actors/runs/{e['run_id']}" if e.get("run_id") else None}


# ---------------------------------------------------------------------------------------------- places along a route
def along(engine, coords: list[list[float]], minute: int, radius: float = 50.0, named_only: bool = True, speed=WALK) -> list[dict]:
    """Places within `radius` m of the route with distance along it and the minute you pass them. Pure engine data."""
    W = engine.W
    pts = np.array([W.proj.xy(lat, lon) for lon, lat in coords])
    seg = np.r_[0.0, np.cumsum(np.hypot(*np.diff(pts, axis=0).T))]
    dense, dist = [], []
    for i in range(len(pts) - 1):
        n = max(1, int((seg[i + 1] - seg[i]) // 10))
        for j in range(n):
            f = j / n; dense.append(pts[i] + (pts[i + 1] - pts[i]) * f); dist.append(seg[i] + (seg[i + 1] - seg[i]) * f)
    dense.append(pts[-1]); dist.append(seg[-1]); D = np.array(dense); A = np.array(dist)
    lo, hi = D.min(0) - radius, D.max(0) + radius
    cand = np.where((W.place_p[:, 0] >= lo[0]) & (W.place_p[:, 0] <= hi[0]) & (W.place_p[:, 1] >= lo[1]) & (W.place_p[:, 1] <= hi[1]))[0]
    out = []
    for idx in cand:
        pl = W.places[idx]
        if named_only and not pl.get("name"): continue
        d = np.hypot(D[:, 0] - pl["p"][0], D[:, 1] - pl["p"][1]); j = int(d.argmin())
        if d[j] > radius: continue
        at = float(A[j]); out.append((pl, round(at), round(float(d[j])), int(minute + at / speed / 60)))
    out.sort(key=lambda t: t[1])
    return out


def live_store(path) -> dict:
    try: return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, ValueError): return {}


def route_evidence(engine, coords, day: int, minute: int, route_key: str, limit: int = 40, travel_mode="walk", travel_options=None) -> dict:
    """Evidence Explorer rows for one route: hours, listed open at your pass minute (or unknown), and provenance."""
    from .hours_check import LIVE_FILE
    store = live_store(LIVE_FILE); rows = []; help_points = []; counts = {"listed": 0, "live": 0, "shopkeeper": 0, "unknown": 0, "stale": 0}
    with engine.lock:
        profile = travel_profile(travel_mode, travel_options)
        ctx = engine.ctx("_evidence", day, minute, profile)
        for pl, at, off, pass_min in along(engine, coords, minute, speed=profile.speed):
            if pl["help"]:
                help_points.append({"id": pl["id"], "name": pl["name"], "hoursKnown": pl["hours"] is not None,
                                    "mappedPublicEntrance": public_entrance(pl), "confirmedOpenNow": False,
                                    "note": "Hours and public entrance access must be established separately; staffing is unverified."})
                continue
            declared = pl["id"] in ctx.overrides; src = pl.get("hours_source")
            if declared:
                ev = {"kind": "shopkeeper", "provider": "shopkeeper", "retrievedAt": None, "stale": False, "note": "Declared tonight on the shop page. Not verified."}
                counts["shopkeeper"] += 1
            elif pl["hours"] is None:
                checked = store.get(pl["id"], {}) if src == "apify-live" else {}
                ev = {"kind": "none", "provider": "apify" if checked else "none", "retrievedAt": checked.get("checked_at"),
                      "stale": is_stale(checked.get("checked_at")), "note": "Unknown hours. They earn no credit in the score; that does not mean closed."}
                counts["unknown"] += 1
            elif src == "osm":
                ev = {"kind": "osm_tag", "provider": "osm", "retrievedAt": None, "stale": False, "note": "OpenStreetMap opening_hours tag; when it was last edited is not in our extract. " + STAFFED}
                counts["listed"] += 1
            elif src == "mock":
                ev = {"kind": "listing_live", "provider": "mock", "retrievedAt": None, "stale": False, "note": "Offline test stand-in for a live check, not a real listing."}
                counts["live"] += 1; counts["listed"] += 1
            elif src == "apify-live":
                e = store.get(pl["id"], {})
                ev = {"kind": "listing_live", "provider": "apify", "url": e.get("url") if str(e.get("url", "")).startswith("http") else None,
                      "retrievedAt": e.get("checked_at"), "runId": e.get("run_id"), "stale": is_stale(e.get("checked_at")), "note": "Checked live after your approval. " + STAFFED}
                counts["live"] += 1; counts["listed"] += 1
            else:
                ev = {"kind": "listing_batch", "provider": "apify-batch", "retrievedAt": pl.get("hours_at"), "stale": is_stale(pl.get("hours_at")),
                      "note": "Published listing hours from the overnight Apify run. " + STAFFED}
                counts["listed"] += 1
            if ev["stale"]: counts["stale"] += 1
            known = declared or pl["hours"] is not None
            rows.append({"id": pl["id"], "name": pl["name"], "cat": pl["cat"], "lngLat": pl["ll"], "atM": at, "offM": off, "passMinute": pass_min % 1440,
                         "hours": pl["hours"], "openAtPass": bool(place_open(engine.W, pl, pass_min, ctx)) if known else None, "evidence": ev})
    return {"route": route_key, "places": rows[:limit], "total": len(rows), "counts": counts, "helpPoints": help_points, "confirmedOpenNow": False,
            "note": "Conditions, not a safety rating. " + STAFFED}
