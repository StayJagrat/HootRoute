"""Synthetic stand-in for the Apify `compass/crawler-google-places` output, derived from the real OSM places.

Used only by --mock runs. It exercises every downstream branch:
  * true records   : same business as an OSM place, jittered position (a few metres), name variants
  * decoys         : same chain name but a different branch 100-400 m away (must NOT be matched)
  * far records    : the right business but >30 m from the OSM point (must stay unmatched)
  * google_only    : businesses that do not exist in OSM (unmatched)
  * hours in many shapes: Google-style day list ("11 AM to 9:30 PM", "Closed", "Open 24 hours", split shifts),
    messy free text ("Mon-Thu 9-9, Fri/Sat til midnight, closed holidays"), junk ("Hours vary"), and no hours at all
  * ~10% of the true records carry *stale* hours that disagree with OSM (so the evaluation number is not trivially 100%)
Hours for places that already have OSM hours are rendered FROM those hours, so the evaluation has a ground truth.
Everything here is fabricated test data. It is labelled `mock:` all the way into hours_evidence.mock.json.
"""
from __future__ import annotations

import base64
import hashlib
import math
import random
from collections import Counter

from hours_common import (DAY_FULL, DAYS, SLOTS_PER_DAY, get_bbox, now_iso, osm_truth_eligible, week_vector)

SEED = 13
CAT_QUERY = {"restaurant": "restaurant", "cafe": "cafe", "fast_food": "fast food restaurant", "bar": "bar", "pub": "pub",
             "nightclub": "night club", "convenience": "convenience store", "pharmacy": "pharmacy", "bank": "bank",
             "bakery": "bakery", "alcohol": "liquor store", "clothes": "clothing store", "hairdresser": "hair salon"}
CAT_NAME = {"restaurant": "Restaurant", "cafe": "Cafe", "fast_food": "Fast food restaurant", "bar": "Bar", "pub": "Pub",
            "nightclub": "Night club", "convenience": "Convenience store", "pharmacy": "Pharmacy", "bank": "Bank",
            "bakery": "Bakery", "alcohol": "Liquor store", "clothes": "Clothing store", "hairdresser": "Hair salon"}

HAND_MESSY = [  # literal strings that show up on websites / listings; no OSM truth needed
    "Mon-Thu 9-9, Fri/Sat til midnight, closed holidays",
    "Open 24 hours",
    "11 AM to 2 AM",
    "Weekdays 7:30am-4pm; weekends 8-3",
    "Tue-Sun 5pm-late",
    "By appointment only",
    "Hours vary",
    "Call for hours",
    "Mon-Fri 8 to 6, Sat 9 to 1, Sun closed",
    "Sunday - Thursday 11am - 10pm, Friday - Saturday 11am - 11pm",
    "Open 7am to 7pm Mon-Sat. Closed Sunday",
    "Mo-Fr 11:00-14:00,17:00-22:00; Sa 12:00-22:00",
    "Daily 10 to midnight",
    "Fri & Sat 5 PM-3 AM",
]
FAKE_A = ["Golden", "Blue", "Lucky", "Mission", "Union", "Pacific", "Cable Car", "Fog City", "Embarcadero", "Tenderloin",
          "Nob Hill", "Market", "Powell", "Sutter", "Bay", "Foggy", "Sunset", "Little"]
FAKE_B = ["Bagels", "Noodle House", "Deli", "Pharmacy", "Tavern", "Espresso", "Taqueria", "Grill", "Mini Mart", "Bakery",
          "Kitchen", "Lounge", "Pizza", "Sushi Bar", "Cafe", "Liquors"]


# ---------------------------------------------------------------- schedule rendering
def vec_to_day_intervals(vec) -> dict[int, list]:
    """336-slot vector -> {day: [(start_min, end_min)]}, Google style (overnight stays on the opening day)."""
    if all(vec):
        return {d: [(0, 1440)] for d in range(7)}
    segs = {d: [] for d in range(7)}
    for d in range(7):
        i = 0
        while i < SLOTS_PER_DAY:
            if vec[d * SLOTS_PER_DAY + i]:
                j = i
                while j < SLOTS_PER_DAY and vec[d * SLOTS_PER_DAY + j]:
                    j += 1
                segs[d].append((i * 30, j * 30)); i = j
            else:
                i += 1
    for d in range(7):
        n = (d + 1) % 7
        if segs[d] and segs[d][-1][1] == 1440 and segs[n] and segs[n][0][0] == 0:
            head = segs[n][0]
            if segs[d][-1][0] >= 720 and head[1] <= 360:
                segs[d][-1] = (segs[d][-1][0], head[1]); segs[n].pop(0)
    return segs


def _t12(m: int, with_ap=True, nbsp=False) -> str:
    m %= 1440
    h, mi = divmod(m, 60)
    ap = "AM" if h < 12 else "PM"
    h12 = h % 12 or 12
    s = f"{h12}" + (f":{mi:02d}" if mi else "")
    return s + (((" " if nbsp else " ") + ap) if with_ap else "")


def _g_interval(s, e, nbsp=False) -> str:
    if (s, e) == (0, 1440):
        return "Open 24 hours"
    same = (s % 1440 // 720) == (e % 1440 // 720) and not (e == 1440)
    return f"{_t12(s, not same, nbsp)} to {_t12(e, True, nbsp)}"


def google_list(segs: dict, nbsp=False) -> list[dict]:
    out = []
    for d in range(7):
        iv = segs[d]
        if not iv:
            h = "Closed"
        elif iv == [(0, 1440)]:
            h = "Open 24 hours"
        else:
            h = ", ".join(_g_interval(s, e, nbsp) for s, e in iv)
        out.append({"day": DAY_FULL[d], "hours": h})
    return out


def _short12(m, ap=True):
    m %= 1440
    h, mi = divmod(m, 60)
    s = f"{h % 12 or 12}" + (f":{mi:02d}" if mi else "")
    return s + (("am" if h < 12 else "pm") if ap else "")


def messy_text(segs: dict, rng: random.Random) -> str:
    """Compact human-style free text rendered from the schedule."""
    style = rng.choice(["compact", "compact", "lines", "h24"])
    names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    runs, d = [], 0
    while d < 7:
        e = d
        while e + 1 < 7 and segs[e + 1] == segs[d]:
            e += 1
        runs.append((d, e, segs[d])); d = e + 1
    if style == "lines":
        lines = []
        for i in range(7):
            iv = segs[i]
            if not iv:
                txt = "Closed"
            elif iv == [(0, 1440)]:
                txt = "Open 24 hours"
            else:
                txt = ", ".join(f"{_t12(a, True, True)} \u2013 {_t12(b, True, True)}" for a, b in iv)
            lines.append(f"{names[i]}: {txt}")
        return "\n".join(lines)
    parts = []
    for a, b, iv in runs:
        label = names[a] if a == b else f"{names[a]}-{names[b]}"
        if not iv:
            parts.append(f"{label} closed")
        elif style == "h24":
            parts.append(f"{label} " + ",".join(f"{s // 60:02d}:{s % 60:02d}-{e // 60:02d}:{e % 60:02d}" for s, e in iv))
        else:
            parts.append(f"{label} " + ", ".join("24 hours" if (s, e) == (0, 1440) else f"{_short12(s)}-{_short12(e)}" for s, e in iv))
    return ", ".join(parts)


# ---------------------------------------------------------------- templates for places without OSM hours
def template_hours(cat: str, rng: random.Random) -> str:
    r = rng
    t = lambda h, m=0: f"{h:02d}:{m:02d}"
    if cat in ("restaurant",):
        o, c = r.choice([(11, 0), (11, 30), (10, 30)]), r.choice([(21, 0), (22, 0), (22, 30)])
        weekend_c = (min(c[0] + 1, 23), c[1])
        if r.random() < 0.2:
            return f"Mo-Th {t(11,30)}-{t(14,30)},{t(17)}-{t(*c)}; Fr-Sa {t(11,30)}-{t(14,30)},{t(17)}-{t(*weekend_c)}; Su {t(17)}-{t(21)}"
        base = f"Mo-Th {t(*o)}-{t(*c)}; Fr-Sa {t(*o)}-{t(*weekend_c)}"
        return base + ("" if r.random() < 0.6 else f"; Su {t(*o)}-{t(*c)}")
    if cat == "cafe":
        o = r.choice([(6, 30), (7, 0), (7, 30), (8, 0)]); c = r.choice([(15, 0), (17, 0), (18, 0)])
        return f"Mo-Fr {t(*o)}-{t(*c)}; Sa-Su {t(o[0] + 1, o[1])}-{t(*c)}"
    if cat == "fast_food":
        return "24/7" if r.random() < 0.06 else f"Mo-Su {t(r.choice([8, 10, 11]))}-{t(r.choice([21, 22, 23]))}"
    if cat in ("bar", "pub"):
        return f"Mo-Th {t(r.choice([15, 16, 17]))}-{t(r.choice([0, 1, 2]))}; Fr-Sa {t(16)}-{t(2)}; Su {t(15)}-{t(0)}".replace("-00:00", "-24:00")
    if cat == "nightclub":
        return f"Th-Sa {t(21)}-{t(2)}"
    if cat == "convenience":
        return "24/7" if r.random() < 0.12 else f"Mo-Su {t(r.choice([6, 7, 8]))}-{t(r.choice([22, 23]))}"
    if cat == "pharmacy":
        return f"Mo-Fr {t(9)}-{t(r.choice([19, 21]))}; Sa {t(10)}-{t(18)}; Su {t(10)}-{t(18)}"
    if cat == "bank":
        return f"Mo-Fr {t(9)}-{t(17)}; Sa {t(9)}-{t(13)}"
    if cat in ("hairdresser", "beauty", "massage"):
        return f"Tu-Sa {t(10)}-{t(19)}; Su {t(11)}-{t(17)}"
    return r.choice([f"Mo-Sa {t(10)}-{t(19)}; Su {t(11)}-{t(17)}", f"Mo-Fr {t(9)}-{t(18)}", f"Mo-Su {t(11)}-{t(20)}", f"Tu-Sa {t(11)}-{t(18)}"])


def _stale(vec_segs: dict, rng: random.Random) -> dict:
    """Make Google disagree with OSM: shift closing times or drop a day."""
    out = {d: list(iv) for d, iv in vec_segs.items()}
    if rng.random() < 0.5:
        shift = rng.choice([60, 90, 120, -60, -120])
        for d, iv in out.items():
            out[d] = [(s, max(s + 60, min(1440, e + shift)) if e != 1440 else e) for s, e in iv]
    else:
        d = rng.randrange(7)
        out[d] = [] if out[d] else [(600, 1080)]
    return out


# ---------------------------------------------------------------- name / geometry helpers
def _variant(name: str, rng: random.Random) -> str:
    r = rng.random()
    if r < 0.68:
        return name
    if r < 0.78:
        return name + rng.choice([" - SF", " San Francisco", " Restaurant", " Cafe"]) if len(name) < 22 else name
    if r < 0.84:
        return name[4:] if name.lower().startswith("the ") else "The " + name
    if r < 0.90:
        return name.replace(" & ", " and ") if " & " in name else name.upper()
    if r < 0.95:
        return name.replace("'", "") if "'" in name else name.lower().title()
    return name + " (Downtown)"


def _offset(lat, lon, dist_m, bearing_rad):
    dlat = dist_m * math.cos(bearing_rad) / 110540
    dlon = dist_m * math.sin(bearing_rad) / (111320 * math.cos(math.radians(lat)))
    return lat + dlat, lon + dlon


def _place_id(*parts) -> str:
    h = hashlib.sha1("|".join(map(str, parts)).encode()).digest()
    return "ChIJ" + base64.urlsafe_b64encode(h).decode().rstrip("=")[:23]


# ---------------------------------------------------------------- main generator
def generate(osm_places: list[dict]) -> list[dict]:
    rng = random.Random(SEED)
    fetched = now_iso()
    named = [p for p in osm_places if p["name"]]
    counts = Counter(p["name"].lower() for p in named)
    chains = [p for p in named if counts[p["name"].lower()] >= 2]
    decoy_ids = {p["id"] for p in rng.sample(chains, min(20, len(chains)))}
    messy_pool = list(HAND_MESSY)
    rng.shuffle(messy_pool)
    items: list[dict] = []

    def base_item(p, title, lat, lon, kind, true_id):
        return {
            "title": title, "placeId": _place_id(p["id"], kind, title), "location": {"lat": round(lat, 7), "lng": round(lon, 7)},
            "address": (f"{p['address']}, San Francisco, CA" if p["address"] else "San Francisco, CA"),
            "categoryName": CAT_NAME.get(p["cat"], (p["cat"] or "Store").replace("_", " ").title()),
            "searchString": CAT_QUERY.get(p["cat"], "restaurant"),
            "permanentlyClosed": False, "temporarilyClosed": False,
            "_mock_kind": kind, "_mock_truth_osm_id": true_id,
        }

    def attach_hours(item, p, own_truth: bool):
        spec = p["hours"] if (own_truth and osm_truth_eligible(p["hours"])) else None
        r = rng.random()
        if r < 0.05:                                                 # google has nothing
            item["openingHours"] = None; return
        if spec is None and r < 0.12 and messy_pool:
            item["openingHoursText"] = messy_pool.pop() if rng.random() < 0.6 else rng.choice(HAND_MESSY); return
        if spec:
            segs = vec_to_day_intervals(week_vector(spec))
            if rng.random() < 0.10:
                segs = _stale(segs, rng); item["_mock_stale"] = True
        else:
            segs = vec_to_day_intervals(week_vector(template_hours(p["cat"], rng)))
        form = rng.random()
        if form < 0.82:
            item["openingHours"] = google_list(segs, nbsp=rng.random() < 0.4)
        else:
            item["openingHoursText"] = messy_text(segs, rng)

    for p in named:
        if p["id"] in decoy_ids:                                    # other branch of the chain, far away
            lat, lon = _offset(p["lat"], p["lon"], rng.uniform(120, 400), rng.uniform(0, 2 * math.pi))
            it = base_item(p, p["name"], lat, lon, "decoy", p["id"])
            it["address"] = "San Francisco, CA"
            attach_hours(it, p, own_truth=False)
            items.append(it); continue
        if rng.random() > 0.90:                                      # not on google at all
            continue
        far = rng.random() < 0.03
        d = rng.uniform(35, 60) if far else abs(rng.gauss(0, 7))
        lat, lon = _offset(p["lat"], p["lon"], d, rng.uniform(0, 2 * math.pi))
        it = base_item(p, _variant(p["name"], rng), lat, lon, "far" if far else "true", p["id"])
        if p["hours"] == "closed":
            it["temporarilyClosed"] = True
        elif rng.random() < 0.03:
            it["permanentlyClosed"] = True
        attach_hours(it, p, own_truth=True)
        items.append(it)

    s, w, n, e = get_bbox()
    for i in range(45):                                              # google-only businesses
        lat, lon = rng.uniform(s, n), rng.uniform(w, e)
        cat = rng.choice(list(CAT_QUERY))
        fake = dict(id=f"x{i}", cat=cat, address="", hours=None)
        it = base_item(fake, f"{rng.choice(FAKE_A)} {rng.choice(FAKE_B)}", lat, lon, "google_only", None)
        attach_hours(it, fake, own_truth=False)
        items.append(it)

    rng.shuffle(items)
    for it in items:
        it["_fetched_at"] = fetched
    return items
