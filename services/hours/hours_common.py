"""Shared helpers for the Streetwise hours-evidence pipeline.

Paths, .env loading, OSM place loading, haversine, and the bridge to the engine's own
`is_open` parser (imported, never copied) plus a strict validator for OSM opening_hours strings.
"""
from __future__ import annotations

import ast
import json
import math
import os
import re
import sys
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]                       # .../StreetWise
CACHE = ROOT / "data" / "cache"
ENGINE_DIR = ROOT / "services" / "engine"
WORLD_PY = ENGINE_DIR / "streetwise_engine" / "world.py"

DAYS = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]
DAY_FULL = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
SLOTS_PER_DAY = 48                            # 30-minute slots
WEEK_SLOTS = 7 * SLOTS_PER_DAY


# ---------------------------------------------------------------- env / io
def load_dotenv(path: Path | None = None) -> None:
    """Tiny .env reader (no dependency). Existing environment variables win."""
    path = path or HERE / ".env"
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.split(" #")[0].strip().strip('"').strip("'")
        if k.strip() and v and k.strip() not in os.environ:
            os.environ[k.strip()] = v


load_dotenv()                                  # services/hours/.env
load_dotenv(HERE.parents[1] / ".env")          # repo-root .env (same keys); the first one found wins


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_json(path: Path):
    return json.loads(Path(path).read_text())


def write_json(path: Path, obj, indent: int | None = 1) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=indent, ensure_ascii=False))


def suffix(mock: bool) -> str:
    return "mock" if mock else "real"


# ---------------------------------------------------------------- geography
def get_bbox() -> tuple[float, float, float, float]:
    """(south, west, north, east); same source of truth as the engine's config.BBOX."""
    f = CACHE / "bbox.json"
    if f.exists():
        return tuple(json.loads(f.read_text()))
    return (37.7690, -122.4250, 37.7990, -122.3910)


def bbox_polygon(pad_deg: float = 0.0005) -> dict:
    """Closed GeoJSON Polygon, coordinates are [lng, lat] as the Apify Actor requires."""
    s, w, n, e = get_bbox()
    s, w, n, e = s - pad_deg, w - pad_deg, n + pad_deg, e + pad_deg
    ring = [[w, s], [e, s], [e, n], [w, n], [w, s]]
    return {"type": "Polygon", "coordinates": [[[round(x, 6), round(y, 6)] for x, y in ring]]}


def haversine_m(lat1, lon1, lat2, lon2) -> float:
    r = 6371008.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


# ---------------------------------------------------------------- OSM places
def load_osm_places() -> list[dict]:
    """Same selection rule as engine World._load_points: shop or amenity tag; id = type[0] + id."""
    out = []
    for el in read_json(CACHE / "osm_points.json"):
        t = el.get("tags", {})
        if not (t.get("shop") or t.get("amenity")):
            continue
        lat = el.get("lat") or el.get("center", {}).get("lat")
        lon = el.get("lon") or el.get("center", {}).get("lon")
        if lat is None:
            continue
        street = " ".join(x for x in (t.get("addr:housenumber"), t.get("addr:street")) if x)
        out.append(dict(id=f"{el['type'][0]}{el['id']}", lat=lat, lon=lon, name=t.get("name"),
                        cat=t.get("amenity") or t.get("shop"), hours=t.get("opening_hours"), address=street,
                        phone=t.get("phone") or t.get("contact:phone")))
    return out


# ---------------------------------------------------------------- engine is_open bridge
def _load_is_open():
    """Import is_open from the engine package. If its heavy deps (numpy/networkx) are missing,
    fall back to compiling the very same function straight out of world.py via ast (still not a copy)."""
    sys.path.insert(0, str(ENGINE_DIR))
    try:
        from streetwise_engine.world import is_open  # type: ignore
        return is_open, "import streetwise_engine.world"
    except Exception:
        src = WORLD_PY.read_text()
        tree = ast.parse(src)
        keep = [n for n in tree.body if (isinstance(n, ast.FunctionDef) and n.name == "is_open")
                or (isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "DAYS" for t in n.targets))]
        ns: dict = {"re": re}
        exec(compile(ast.Module(body=keep, type_ignores=[]), str(WORLD_PY), "exec"), ns)
        return ns["is_open"], "ast-extracted from world.py"


is_open, IS_OPEN_SOURCE = _load_is_open()


@lru_cache(maxsize=None)
def week_vector(spec: str | None) -> tuple:
    """336 booleans, Monday 00:00 first, 30 minute slots, exactly as the engine would answer (None -> closed)."""
    return tuple(bool(is_open(spec, d, m * 30)) for d in range(7) for m in range(SLOTS_PER_DAY))


def agreement(a: str | None, b: str | None) -> float:
    va, vb = week_vector(a), week_vector(b)
    return sum(x == y for x, y in zip(va, vb)) / WEEK_SLOTS


# ---------------------------------------------------------------- strict OSM validator
_D = r"(?:Mo|Tu|We|Th|Fr|Sa|Su)"
_DAYSPEC = rf"{_D}(?:-{_D})?(?:,{_D}(?:-{_D})?)*"
_SPAN = r"\d{2}:\d{2}-\d{2}:\d{2}"
_RULE = re.compile(rf"^(?:(?P<days>{_DAYSPEC})\s+)?(?P<body>off|closed|{_SPAN}(?:,{_SPAN})*)$")


def _days_of(spec: str) -> set[int]:
    days: set[int] = set()
    for part in spec.split(","):
        if "-" in part:
            a, b = DAYS.index(part[:2]), DAYS.index(part[3:5])
            days |= {(a + i) % 7 for i in range(((b - a) % 7) + 1)}
        else:
            days.add(DAYS.index(part[:2]))
    return days


def _expected_vector(spec: str):
    """Independent reading of a *grammar-valid* spec (union of spans; overnight spills into the next day)."""
    if spec == "24/7":
        return [True] * WEEK_SLOTS
    v = [False] * WEEK_SLOTS
    for rule in [r.strip() for r in spec.split(";") if r.strip()]:
        m = _RULE.match(rule)
        days = _days_of(m.group("days")) if m.group("days") else set(range(7))
        if m.group("body") in ("off", "closed"):
            continue
        for h1, m1, h2, m2 in re.findall(r"(\d{2}):(\d{2})-(\d{2}):(\d{2})", m.group("body")):
            s, e = int(h1) * 60 + int(m1), int(h2) * 60 + int(m2)
            for d in days:
                if e <= s:
                    spans = [(d, s, 1440), ((d + 1) % 7, 0, e)]
                else:
                    spans = [(d, s, e)]
                for dd, a, b in spans:
                    for slot in range(SLOTS_PER_DAY):
                        if a <= slot * 30 < b:
                            v[dd * SLOTS_PER_DAY + slot] = True
    return v


def validate_osm_hours(spec) -> tuple[bool, str]:
    """Strict check that `spec` is in the subset the engine reads AND that the engine reads it as intended.

    1. grammar: 24/7 | off | rules 'Mo-Fr,Su HH:MM-HH:MM[,HH:MM-HH:MM]' separated by ';' (times 00:00..24:00, start != end)
    2. engine round-trip: is_open over all 336 half-hour slots equals an independent reading of the grammar
    3. sanity: something is open unless the spec is explicitly 'off'
    """
    if not isinstance(spec, str) or not spec.strip():
        return False, "empty"
    spec = spec.strip()
    if len(spec) > 400:
        return False, "too long"
    if spec == "24/7":
        pass
    else:
        rules = [r.strip() for r in spec.split(";") if r.strip()]
        if not rules:
            return False, "no rules"
        for rule in rules:
            m = _RULE.match(rule)
            if not m:
                return False, f"rule outside supported syntax: {rule!r}"
            if m.group("body") in ("off", "closed"):
                continue
            for h1, m1, h2, m2 in re.findall(r"(\d{2}):(\d{2})-(\d{2}):(\d{2})", m.group("body")):
                h1, m1, h2, m2 = int(h1), int(m1), int(h2), int(m2)
                if h1 > 23 or m1 > 59 or m2 > 59 or h2 > 24 or (h2 == 24 and m2 != 0):
                    return False, f"time out of range in {rule!r}"
                if h1 * 60 + m1 == h2 * 60 + m2:
                    return False, f"zero/24h span must be written 00:00-24:00 or 24/7: {rule!r}"
    try:
        got = week_vector(spec)
    except Exception as ex:  # engine choked
        return False, f"engine raised {ex!r}"
    exp = _expected_vector(spec)
    if list(got) != exp:
        return False, "engine reads it differently than the grammar says"
    if spec not in ("off", "closed") and not any(got) and not all(
            _RULE.match(r.strip()).group("body") in ("off", "closed") for r in spec.split(";") if r.strip()):
        return False, "nothing is ever open"
    return True, "ok"


def osm_truth_eligible(spec) -> bool:
    """OSM value usable as ground truth: strict-valid and open at least once a week."""
    ok, _ = validate_osm_hours(spec)
    return ok and any(week_vector(spec))
