"""Checker's evidence tools: find places on a route whose hours are unknown, and check their published listing with a live
Apify run (Google Maps actor). Results become hours evidence the deterministic engine re-scores with.

What a check can and cannot say:
- "hours found"   : the public listing publishes a weekly schedule. It is a listing, not proof the shop is staffed tonight.
- "no hours"      : the listing exists but publishes no schedule. Stays unknown (never "closed", never "unsafe").
- "closed"        : the listing says permanently or temporarily closed.
- "not found"     : no listing matched by name within 80 m. Stays unknown.
Every result carries its source URL and the time it was retrieved.
"""
from __future__ import annotations

import json
import logging
import math
import sys
import time
from pathlib import Path

import httpx
import numpy as np

from . import evidence
from .config import env

log = logging.getLogger("hootroute.hours")
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "services" / "hours"))
LIVE_FILE = Path(env("HOURS_LIVE_FILE", str(ROOT / "data" / "cache" / "hours_live.json")))
ACTOR = "compass~crawler-google-places"
USEFUL = {"cafe", "restaurant", "fast_food", "bar", "pub", "convenience", "supermarket", "pharmacy", "ice_cream", "bakery", "deli", "hotel", "fuel", "kiosk"}


# ---------------------------------------------------------------------------------------------------- unknowns
def unknowns(engine, coords: list[list[float]], day: int, minute: int, limit: int = 5, radius: float = 50.0) -> list[dict]:
    """Named places within `radius` m of the route whose hours are unknown, most useful first (shops people can walk into,
    near the longest empty stretch). Pure engine data, no network."""
    W = engine.W; WALK = 1.35
    pts = np.array([W.proj.xy(lat, lon) for lon, lat in coords])
    seg = np.r_[0.0, np.cumsum(np.hypot(*np.diff(pts, axis=0).T))]
    dense, along = [], []
    for i in range(len(pts) - 1):
        n = max(1, int((seg[i + 1] - seg[i]) // 10))
        for j in range(n):
            f = j / n; dense.append(pts[i] + (pts[i + 1] - pts[i]) * f); along.append(seg[i] + (seg[i + 1] - seg[i]) * f)
    dense.append(pts[-1]); along.append(seg[-1]); D = np.array(dense); A = np.array(along)
    lo, hi = D.min(0) - radius, D.max(0) + radius
    cand = np.where((W.place_p[:, 0] >= lo[0]) & (W.place_p[:, 0] <= hi[0]) & (W.place_p[:, 1] >= lo[1]) & (W.place_p[:, 1] <= hi[1]))[0]
    out = []
    for idx in cand:
        pl = W.places[idx]
        if pl["hours"] is not None or pl["help"] or not pl.get("name"): continue
        d = np.hypot(D[:, 0] - pl["p"][0], D[:, 1] - pl["p"][1]); j = int(d.argmin())
        if d[j] > radius: continue
        at = float(A[j])
        out.append(dict(id=pl["id"], name=pl["name"], cat=pl["cat"], lngLat=pl["ll"], atM=round(at), offM=round(float(d[j])),
                        passMinute=int(minute + at / WALK / 60) % 1440, useful=pl["cat"] in USEFUL))
    out.sort(key=lambda p: (not p["useful"], p["offM"] > 25, p["atM"]))
    return out[:limit]


# ---------------------------------------------------------------------------------------------------- live check
def _polygon(places: list[dict], pad_deg: float = 0.002) -> dict:
    lons = [p["lngLat"][0] for p in places]; lats = [p["lngLat"][1] for p in places]
    w, e, s, n = min(lons) - pad_deg, max(lons) + pad_deg, min(lats) - pad_deg, max(lats) + pad_deg
    ring = [[w, s], [e, s], [e, n], [w, n], [w, s]]
    return {"type": "Polygon", "coordinates": [[[round(x, 6), round(y, 6)] for x, y in ring]]}


def _meters(a, b) -> float:
    dy = (a[1] - b[1]) * 111_320; dx = (a[0] - b[0]) * 111_320 * math.cos(math.radians(a[1]))
    return math.hypot(dx, dy)


def _match(place: dict, items: list[dict]) -> dict | None:
    from match_osm import name_sim
    best, best_s = None, 0.0
    for it in items:
        loc = it.get("location") or {}
        if not isinstance(loc.get("lat"), (int, float)): continue
        if _meters(place["lngLat"], (loc["lng"], loc["lat"])) > 80: continue
        s = name_sim(place["name"], it.get("title"))
        if s > best_s: best, best_s = it, s
    return best if best_s >= 0.6 else None


TERMINAL = {"SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"}


def run_actor(places: list[dict], timeout_s: int = 100, max_usd: float = 0.5, client: httpx.Client | None = None) -> tuple[list[dict], dict]:
    """One Apify actor run that searches every place name inside a box around them. Returns (items, run info with the run id).

    Starts the run, waits for it (up to `timeout_s`), aborts it if it is still running, then reads its dataset. The charge cap
    is enforced by Apify (`maxTotalChargeUsd`)."""
    token = env("APIFY_TOKEN")
    if not token: raise RuntimeError("APIFY_TOKEN is not configured")
    names = list(dict.fromkeys(p["name"] for p in places))[:8]
    run_input = {"searchStringsArray": names, "customGeolocation": _polygon(places), "maxCrawledPlacesPerSearch": 3,
                 "language": "en", "skipClosedPlaces": False}
    t0 = time.time(); api = "https://api.apify.com/v2"; own = client is None
    c = client or httpx.Client(timeout=75, headers={"Authorization": f"Bearer {token}"})
    try:
        r = c.post(f"{api}/acts/{ACTOR}/runs", params={"timeout": timeout_s, "maxTotalChargeUsd": max_usd, "waitForFinish": 60}, json=run_input)
        r.raise_for_status(); run = r.json().get("data") or {}
        rid = run.get("id")
        if not rid: raise RuntimeError("Apify did not return a run id")
        while run.get("status") not in TERMINAL and time.time() - t0 < timeout_s + 15:
            r = c.get(f"{api}/actor-runs/{rid}", params={"waitForFinish": 30}); r.raise_for_status(); run = r.json().get("data") or run
        info = {"actor": ACTOR.replace("~", "/"), "runId": rid, "consoleUrl": f"https://console.apify.com/actors/runs/{rid}", "status": run.get("status"),
                "input": run_input, "seconds": round(time.time() - t0, 1), "items": 0, "usageUsd": run.get("usageTotalUsd")}
        if run.get("status") not in TERMINAL:
            try: c.post(f"{api}/actor-runs/{rid}/abort")
            except httpx.HTTPError: pass
            raise TimeoutError(f"Apify run {rid} did not finish within {timeout_s} s and was aborted")
        if run.get("status") != "SUCCEEDED": raise RuntimeError(f"Apify run {rid} ended {run.get('status')}")
        r = c.get(f"{api}/datasets/{run['defaultDatasetId']}/items", params={"clean": "true", "format": "json", "limit": 100}); r.raise_for_status()
        items = r.json(); items = items if isinstance(items, list) else []
        info["items"] = len(items)
        log.info("apify run %s %s: %d items in %.1fs", rid, run.get("status"), len(items), info["seconds"])
        return items, info
    finally:
        if own: c.close()


def mock_mode() -> bool: return env("HOURS_CHECK_MOCK") == "1"


def _mock_items(places: list[dict]) -> list[dict]:
    """HOURS_CHECK_MOCK=1 (tests only): a deterministic stand-in for the actor, labelled as such in every result."""
    out = []
    for i, p in enumerate(places):
        loc = {"lng": p["lngLat"][0], "lat": p["lngLat"][1]}
        if i % 3 == 0: out.append({"title": p["name"], "location": loc, "url": "mock://listing", "openingHours": [{"day": d, "hours": "7 AM to 1 AM"} for d in ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")]})
        elif i % 3 == 1: out.append({"title": p["name"], "location": loc, "url": "mock://listing"})
    return out


def check(places: list[dict]) -> dict:
    """Check each place's published listing. Never raises: failures come back as an honest status the UI can show."""
    if not places: return {"ok": True, "results": [], "run": None, "note": "No place with unknown hours on this route."}
    mock = mock_mode()
    try:
        items, run = (_mock_items(places), {"actor": "MOCK (tests only)", "runId": None, "consoleUrl": None, "seconds": 0.0, "items": len(places), "status": "MOCK"}) if mock else run_actor(places)
    except Exception as e:      # timeout, no token, network, HTTP error, unexpected response
        log.warning("hours check failed: %s", e)
        return {"ok": False, "results": [dict(id=p["id"], name=p["name"], status="check failed", hours=None, checkedAt=time.strftime("%Y-%m-%dT%H:%M:%S%z")) for p in places], "run": None,
                "mock": mock, "note": f"The live check did not finish ({type(e).__name__}: {str(e)[:120]}). Hours stay unknown; the route is unchanged."}
    from match_osm import source_text
    from parse_hours import parse_rules
    now = time.strftime("%Y-%m-%dT%H:%M:%S%z"); results = []
    for p in places:
        it = _match(p, items)
        if not it:
            results.append(dict(id=p["id"], name=p["name"], status="not found", hours=None, source=None, checkedAt=now)); continue
        text = source_text(it); parsed = parse_rules(text) if text else {"opening_hours": None, "confidence": 0}
        spec = parsed.get("opening_hours"); conf = parsed.get("confidence", 0)
        status = "closed" if spec == "off" else "hours found" if spec and conf >= 0.6 else "no hours"
        results.append(dict(id=p["id"], name=p["name"], status=status, hours=spec if status != "no hours" else None, sourceText=text, confidence=conf,
                            source=it.get("url") or "Google Maps listing via Apify", listingName=it.get("title"), checkedAt=now))
    return {"ok": True, "results": results, "run": run, "mock": mock,
            "note": "Listed hours from public listings. A listing is not proof a place is staffed at that minute."}


# ---------------------------------------------------------------------------------------------------- evidence
def apply(engine, results: list[dict], run: dict | None = None) -> int:
    """Write found hours into the engine (and data/cache/hours_live.json so a restart keeps them). Returns how many changed."""
    W = engine.W; changed = 0
    with engine.lock:
        for r in results:
            if r["status"] not in ("hours found", "closed") or not r.get("hours"): continue
            i = W.place_index.get(r["id"])
            if i is None or W.places[i]["hours"] is not None: continue
            W.places[i]["hours"] = r["hours"]; changed += 1
            W.places[i]["hours_source"] = "mock" if str(r.get("source") or "").startswith("mock://") else "apify-live"
        if changed: engine._quick.clear()
    record(results, run)
    return changed


def record(results: list[dict], run: dict | None = None) -> bool:
    """Remember every completed check (found, no hours, not found, closed) with its source, time and run id, so a repeat
    within EVIDENCE_TTL_HOURS reuses it instead of paying again. Failed checks are not remembered."""
    store = json.loads(LIVE_FILE.read_text()) if LIVE_FILE.exists() else {}; n = 0
    for r in results:
        kind = evidence.KIND_OF_STATUS.get(r.get("status"))
        if kind in (None, "check_failed") or str(r.get("source") or "").startswith("mock://"): continue     # test stand-ins are never kept
        store[r["id"]] = {"opening_hours": r.get("hours") if kind in ("published_hours", "listed_closed") else None, "kind": kind, "name": r.get("name"),
                          "source": "apify-live", "url": r.get("source"), "checked_at": r.get("checkedAt"), "confidence": r.get("confidence"),
                          "listing_name": r.get("listingName"), "run_id": (run or {}).get("runId")}
        n += 1
    if n:
        try: LIVE_FILE.parent.mkdir(parents=True, exist_ok=True); LIVE_FILE.write_text(json.dumps(store, indent=1))
        except OSError: log.warning("could not persist live hours"); return False
    return bool(n)


def load_live(engine) -> int:
    """At boot: re-apply hours found by earlier live checks."""
    if not LIVE_FILE.exists(): return 0
    W = engine.W; n = 0
    for pid, e in json.loads(LIVE_FILE.read_text()).items():
        i = W.place_index.get(pid)
        if i is not None and W.places[i]["hours"] is None and e.get("opening_hours"):
            W.places[i]["hours"] = e["opening_hours"]; W.places[i]["hours_source"] = "apify-live"; n += 1
    return n


# ---------------------------------------------------------------------------------------------------- the investigation
async def investigate(engine, places: list[dict], budget=None) -> dict:
    """Sherlock's bounded investigation: reuse recent checks, spend at most one paid run on the rest (if the daily budget
    allows), apply what was found, and return every result as Evidence with its source and time."""
    import asyncio
    store = evidence.live_store(LIVE_FILE); mock = mock_mode()
    reused = [evidence.result_from_store(p["id"], store[p["id"]]) for p in places if not mock and evidence.reusable(store.get(p["id"]))]
    fresh = [p for p in places if p["id"] not in {r["id"] for r in reused}]
    run = None; results: list[dict] = []; ok = True; note = ""
    if fresh:
        if not mock and budget is not None and not budget.spend():
            ok = False; note = "Today's budget for paid listing checks is used up. Hours stay unknown; nothing was changed."
            results = [dict(id=p["id"], name=p["name"], status="check failed", hours=None) for p in fresh]
        else:
            res = await asyncio.to_thread(check, fresh); results, run, ok, note = res["results"], res["run"], res["ok"], res["note"]
    if reused: note = (note + " " if note else "") + f"Reused {len(reused)} check{'s' if len(reused) != 1 else ''} from the last {evidence.TTL_HOURS:g} h (no new charge)."
    allr = reused + results
    changed = await asyncio.to_thread(apply, engine, results, run) if ok and results else 0       # reused evidence is already in the engine
    ev = [evidence.from_result(r, run, mock, reused=r in reused) for r in allr]
    return {"ok": ok or bool(reused), "results": allr, "run": run, "mock": mock, "note": note or "Nothing to check.", "changed": changed, "evidence": ev,
            "reused": len(reused), "checked": len(results)}
