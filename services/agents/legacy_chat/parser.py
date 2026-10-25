"""Deterministic request parser. 'Walk me from Powell BART to Civic Center at 11:40pm' -> origin, destination, day, minute.

No network and no LLM needed. An LLM (ASI:One) may optionally pull the raw strings out of a messy sentence
(see llm_extract), but resolution to real landmarks and the time maths always happen here.
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

DAY_WORDS = {"monday": 0, "mon": 0, "tuesday": 1, "tues": 1, "tue": 1, "wednesday": 2, "wed": 2, "thursday": 3, "thurs": 3, "thur": 3, "thu": 3,
             "friday": 4, "fri": 4, "saturday": 5, "sat": 5, "sunday": 6, "sun": 6}
DAY_RE = re.compile(r"\b(" + "|".join(sorted(DAY_WORDS, key=len, reverse=True)) + r")\b")
T12 = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)(?![a-z])")
T24 = re.compile(r"\b([01]?\d|2[0-3]):([0-5]\d)\b")
FILLER = re.compile(r"\b(at|on|around|about|by|@|tonight|today|this evening|please|thanks|thank you|leaving|leave|starting|depart|departing|after|before|for)\b")
LEAD = re.compile(r"^(?:(?:hey|hi|hello)[ ,]+)?(?:(?:please|can you|could you|would you|i need you to|i want to|i need to|i'd like to)\s+)*"
                  r"(?:walk|take|get|guide|navigate|route|plan|find|show|help|go|head|directions?|how do i get)?(?:\s+(?:me|us))?(?:\s+a)?(?:\s+(?:safe|safest|safer))?"
                  r"(?:\s+(?:walk|route|way|path|directions?))?(?:\s+me)?\s*")
SF = ZoneInfo("America/Los_Angeles")


@dataclass
class Point:
    name: str; lat: float; lon: float; score: float = 1.0; source: str = "landmark"


@dataclass
class Parsed:
    origin: Point | None = None; dest: Point | None = None
    day: int = 4; minute: int = 22 * 60 + 50
    notes: list[str] = field(default_factory=list); errors: list[str] = field(default_factory=list)
    origin_text: str = ""; dest_text: str = ""

    @property
    def ok(self): return self.origin is not None and self.dest is not None and not self.errors


def _norm(s: str) -> str:
    s = s.lower().replace("&", " and ").replace("st.", "st")
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = re.sub(r"\b(the|a|an|station|stn|my|near|nearby)\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def parse_time(text: str, now: datetime | None = None) -> tuple[int | None, int | None, str, list[str]]:
    """Returns (day, minute, remaining_text, notes). Minutes before 5 AM are read as late-night of the same service day (+1440)."""
    t = text.lower(); notes = []; now = now or datetime.now(SF)
    day = None; minute = None
    m = DAY_RE.search(t)
    if m: day = DAY_WORDS[m.group(1)]; t = t[:m.start()] + " " + t[m.end():]
    if "tomorrow" in t: day = (now.weekday() + 1) % 7; t = t.replace("tomorrow", " ")
    if re.search(r"\b(midnight)\b", t): minute = 1440; t = re.sub(r"\bmidnight\b", " ", t)
    elif re.search(r"\bnoon\b", t): minute = 720; t = re.sub(r"\bnoon\b", " ", t)
    else:
        m = T12.search(t)
        if m:
            h = int(m.group(1)) % 12; mm = int(m.group(2) or 0); h += 12 if m.group(3).startswith("p") else 0
            minute = h * 60 + mm; t = t[:m.start()] + " " + t[m.end():]
        else:
            m = T24.search(t)
            if m: minute = int(m.group(1)) * 60 + int(m.group(2)); t = t[:m.start()] + " " + t[m.end():]
    if minute is not None and minute < 5 * 60:
        minute += 1440
        if day is not None: day = (day - 1) % 7        # "1am Saturday" is the small hours of Saturday, i.e. Friday's service day + 24h
        notes.append("Times before 5 AM are scored as late night of the previous day's evening.")
    if minute is None and re.search(r"\btonight\b", text.lower()): minute = 22 * 60; notes.append("'tonight' read as 10:00 PM.")
    if day is None and (minute is not None or "tonight" in text.lower() or "today" in text.lower()): day = now.weekday()
    return day, minute, t, notes


def split_places(t: str) -> tuple[str, str]:
    t = t.replace("→", " to ").replace("->", " to ")
    t = FILLER.sub(" ", t); t = re.sub(r"\s+", " ", t).strip(" ,.?!")
    m = re.search(r"\bfrom\s+(.+?)\s+to\s+(.+)$", t)
    if m: return m.group(1).strip(), m.group(2).strip()
    m = re.search(r"\bto\s+(.+?)\s+from\s+(.+)$", t)          # "take me to X from Y"
    if m: return m.group(2).strip(), m.group(1).strip()
    m = re.search(r"\bfrom\s+(.+?)\s+(?:towards?|into|until)\s+(.+)$", t)
    if m: return m.group(1).strip(), m.group(2).strip()
    t2 = LEAD.sub("", t, count=1).strip()
    m = re.match(r"^(.+?)\s+to\s+(.+)$", t2)
    if m: return m.group(1).strip(), m.group(2).strip()
    m = re.match(r"^to\s+(.+)$", t2)
    return ("", m.group(1).strip()) if m else ("", "")


LATLON = re.compile(r"^\(?\s*(-?\d{1,2}\.\d+)\s*,\s*(-?\d{1,3}\.\d+)\s*\)?$")


def resolve(name: str, landmarks: list[dict], places: list | None = None, threshold: float = 0.62) -> tuple[Point | None, list[str]]:
    """Fuzzy-match a free-text place against engine landmarks (then, optionally, named places). Returns (best, suggestions)."""
    q = _norm(name)
    if not q: return None, []
    m = LATLON.match(name.strip())
    if m: return Point(f"{m.group(1)}, {m.group(2)}", float(m.group(1)), float(m.group(2)), 1.0, "coordinates"), []
    qt = set(q.split()); scored = []
    for lm in landmarks:
        n = _norm(lm["name"]); nt = set(n.split())
        if q == n: s = 1.0
        elif qt and (qt <= nt or nt <= qt): s = 0.9 + 0.05 * (len(qt & nt) / max(len(qt | nt), 1))
        elif q in n or n in q: s = 0.85
        else: s = max(difflib.SequenceMatcher(None, q, n).ratio(), 0.8 * max((difflib.SequenceMatcher(None, w, x).ratio() for w in qt for x in nt), default=0) * (len(qt & nt) > 0 or 1))
        scored.append((s, lm))
    scored.sort(key=lambda x: -x[0])
    sugg = [lm["name"] for _, lm in scored[:4]]
    if scored and scored[0][0] >= threshold:
        s, lm = scored[0]; return Point(lm["name"], lm["lat"], lm["lon"], s, "landmark"), sugg
    if places and len(q) >= 4:        # engine /api/places rows: [id, lat, lon, name, cat, open, declared]
        hits = [p for p in places if p[3] and (q == _norm(p[3]) or q in _norm(p[3]))]
        if hits:
            hits.sort(key=lambda p: len(p[3])); p = hits[0]; return Point(p[3], p[1], p[2], 0.8, "place"), sugg
    return None, sugg


def parse_request(text: str, landmarks: list[dict], places: list | None = None, now: datetime | None = None,
                  llm: dict | None = None) -> Parsed:
    """Deterministic parse. `llm` may supply {'origin','destination','time'} strings that are only used for fields the parser could not find."""
    now = now or datetime.now(SF); out = Parsed()
    day, minute, rest, notes = parse_time(text, now); out.notes += notes
    o_txt, d_txt = split_places(rest)
    if llm:
        if not o_txt and llm.get("origin"): o_txt = str(llm["origin"]); out.notes.append("Origin extracted with ASI:One.")
        if not d_txt and llm.get("destination"): d_txt = str(llm["destination"]); out.notes.append("Destination extracted with ASI:One.")
        if minute is None and llm.get("time"):
            d2, m2, _, n2 = parse_time(str(llm["time"]), now)
            if m2 is not None: minute = m2; day = day if day is not None else d2; out.notes += n2
    if minute is None:
        minute = now.hour * 60 + now.minute; day = now.weekday() if day is None else day
        out.notes.append(f"No time given, so I used the current San Francisco time ({now.strftime('%a %I:%M %p').replace(' 0', ' ')}).")
    elif day is None:
        day = now.weekday(); out.notes.append("No day given, so I used today.")
    out.day, out.minute, out.origin_text, out.dest_text = day, minute, o_txt, d_txt
    if not o_txt or not d_txt:
        out.errors.append("I need both a start and an end, for example: Walk me from Powell BART to Civic Center at 11:40pm."); return out
    for label, txt, attr in (("start", o_txt, "origin"), ("end", d_txt, "dest")):
        pt, sugg = resolve(txt, landmarks, places)
        if pt is None: out.errors.append(f"I could not find your {label} \"{txt}\". Places I know: {', '.join(sugg) or 'none'}.")
        else: setattr(out, attr, pt)
    return out


def looks_like_route_request(text: str) -> bool:
    t = text.lower()
    return bool(re.search(r"\bto\b|->|→", t) and (re.search(r"\bfrom\b|\bwalk\b|\broute\b|\bnavigate\b|\bto\b", t)))


async def llm_extract(text: str, landmark_names: list[str]) -> dict | None:
    """OPTIONAL: ask ASI:One for raw strings. Returns None on any problem; the deterministic parser must work without it."""
    import json, os
    import httpx
    key = os.environ.get("ASI1_API_KEY", "").strip()
    if not key: return None
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post("https://api.asi1.ai/v1/chat/completions", headers={"Authorization": f"Bearer {key}"},
                             json=dict(model="asi1", temperature=0, messages=[
                                 dict(role="system", content="Extract a walking request. Reply with ONLY JSON: {\"origin\": str|null, \"destination\": str|null, \"time\": str|null}. "
                                      "time is the clock time/day as the user wrote it. Known San Francisco places: " + "; ".join(landmark_names)),
                                 dict(role="user", content=text)]))
            r.raise_for_status(); content = r.json()["choices"][0]["message"]["content"]
        m = re.search(r"\{.*\}", content, re.S)
        return json.loads(m.group(0)) if m else None
    except Exception:
        return None
