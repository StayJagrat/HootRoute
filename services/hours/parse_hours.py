"""Stage 3: turn messy opening-hours text into OSM `opening_hours` strings the engine's `is_open` can read.

Two parsers:
  * rules  - deterministic regex/tokeniser, no network. Used by --mock and as the offline fallback.
  * claude - Anthropic API (default model claude-haiku-5-5, override with HOURS_CLAUDE_MODEL), strict JSON.
Both return {"opening_hours": str|None, "confidence": 0..1, "notes": str}. Every non-null value is validated with
hours_common.validate_osm_hours (strict grammar + round trip through the engine's own is_open).
Rule: no source text -> null. Never guess.

CLI:  python parse_hours.py [--mock] [--parser rules|claude|auto] [--matches PATH] [--out PATH] [--only-missing]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hours_common import (CACHE, DAY_FULL, DAYS, HERE, now_iso, read_json, suffix, validate_osm_hours,  # noqa: E402
                          write_json)

DEFAULT_MODEL = "claude-haiku-5-5"
CLAUDE_CACHE = CACHE / "hours_parse_cache_claude.json"

# ====================================================================== text -> intervals (rules parser)
_DAYWORDS = {
    0: ["monday", "mon"], 1: ["tuesday", "tues", "tue"], 2: ["wednesday", "weds", "wed"],
    3: ["thursday", "thurs", "thur", "thu"], 4: ["friday", "fri"], 5: ["saturday", "sat"], 6: ["sunday", "sun"],
}
_DAYLOOKUP = {w: i for i, ws in _DAYWORDS.items() for w in ws}
_DAYALT = "|".join(sorted(_DAYLOOKUP, key=len, reverse=True))
# 2-letter OSM-style names only when capitalised (so the English word "we" never counts as Wednesday)
_DAY1 = rf"(?:(?i:{_DAYALT})s?|(?-i:Mo|Tu|We|Th|Fr|Sa|Su))(?![A-Za-z])"
_DAYRANGE = re.compile(rf"(?P<d1>{_DAY1})(?:\s*-\s*(?P<d2>{_DAY1}))?", re.I)
_TIME = r"(?:\d{1,2}(?::\d{2})?\s*(?:[ap]\.?m\.?)?|noon|midnight)"
_RANGE = re.compile(rf"(?:(?P<a>{_TIME})\s*)?-\s*(?P<b>{_TIME})", re.I)
_H24 = re.compile(r"24\s*/\s*7|24\s*(?:hours?|hrs?)\b|round\s+the\s+clock|all\s+day|all\s+night", re.I)
_GROUPWORDS = re.compile(r"weekdays?|weekends?|daily|everyday|every\s+day|7\s+days(?:\s+a\s+week)?|seven\s+days", re.I)
_CLOSED = re.compile(r"closed|off\b", re.I)
_WORD = re.compile(r"[A-Za-z]+")
_FILLER = {"open", "opens", "hours", "hrs", "from", "on", "every", "and", "the", "at", "is", "are", "only", "also", "we",
           "day", "days", "a", "week", "in", "of", "to", "daily", "regular", "business", "hour", "except", "am", "pm"}
_HOLIDAY = re.compile(r"(?:(?:closed|off)\s+(?:on\s+)?(?:public\s+|major\s+|bank\s+|national\s+|us\s+)?holidays?"
                      r"|(?:public\s+|major\s+|bank\s+|national\s+)?holidays?\s*[:\-]?\s*(?:closed|off)?|\bph\b(?:\s*(?:off|closed))?)", re.I)
_NEVER = re.compile(r"permanently\s+closed|closed\s+permanently|temporarily\s+closed|closed\s+temporarily|out\s+of\s+business", re.I)
_NOINFO = re.compile(r"by\s+appointment|appointment\s+only|hours\s+(?:vary|may\s+vary)|call\s+(?:for|ahead)|varies|seasonal|not\s+available|n/?a\b|unknown|tbd", re.I)


def _norm(text: str) -> str:
    text = text.replace(" ", " ").replace(" ", " ").replace(" ", " ").replace("\xa0", " ")
    text = re.sub(r"[‒–—−]", "-", text)
    text = re.sub(r"\b(?:until|till|til|thru|through|to)\b", "-", text, flags=re.I)
    return text


def _time(tok: str) -> dict:
    t = tok.strip().lower().replace(".", "")
    if t == "noon":
        return dict(min=720, ap="p", word="noon", h=12, raw=tok)
    if t == "midnight":
        return dict(min=0, ap="a", word="midnight", h=12, raw=tok)
    m = re.match(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm|a|p)?$", t)
    h, mi, ap = int(m.group(1)), int(m.group(2) or 0), (m.group(3) or "")[:1] or None
    return dict(h=h, mi=mi, ap=ap, word=None, raw=tok, lead0=t[0] == "0" and len(t) > 1 and t[1].isdigit(), colon=m.group(2) is not None)


def _to_min(h, mi, ap):
    if h > 24 or mi > 59:
        return None
    if ap == "a":
        return (0 if h == 12 else h) * 60 + mi
    if ap == "p":
        return (h if h == 12 else h + 12) * 60 + mi
    return h * 60 + mi


def _guess_ap(h: int) -> str:
    """No AM/PM given: 7..12 reads as morning/noon, 1..6 as afternoon/evening."""
    return "a" if (h >= 7 and h != 12) else "p"


def _resolve(a: dict | None, b: dict, prev_start: int | None):
    """-> (start, end, penalty, note) in minutes, or None. end may be <= start (overnight) or 1440 (midnight)."""
    def pick_end(b, start):
        if b.get("word") == "midnight":
            return 1440
        if b.get("word") == "noon":
            return 720
        if b["ap"]:
            return _to_min(b["h"], b["mi"], b["ap"])
        cands = sorted({_to_min(b["h"], b["mi"], "a"), _to_min(b["h"], b["mi"], "p")})
        gt = [c for c in cands if c > start]
        return min(gt) if gt else cands[0]

    if a is None:                                                   # "fri/sat til midnight": inherit previous start
        if prev_start is None or (b["ap"] is None and not b.get("word")):
            return None
        end = pick_end(b, prev_start)
        return prev_start, (end or 1440), 0.2, "end-only range, start inherited from previous rule"

    pen, note = 0.0, ""
    a_word, b_word = a.get("word"), b.get("word")
    if a_word or b_word:
        if a_word:
            start = 720 if a_word == "noon" else 0
        elif a["ap"]:
            start = _to_min(a["h"], a["mi"], a["ap"])
        else:
            start, pen, note = _to_min(a["h"], a["mi"], _guess_ap(a["h"])), 0.1, "start meridiem inferred"
        end = pick_end(b, start)
    else:
        aa, ba = a["ap"], b["ap"]
        h24 = (not aa and not ba) and (a["lead0"] or b["lead0"] or a["h"] >= 13 or b["h"] >= 13)
        if h24:
            start, end = _to_min(a["h"], a["mi"], None), _to_min(b["h"], b["mi"], None)
        elif aa and ba:
            start, end = _to_min(a["h"], a["mi"], aa), _to_min(b["h"], b["mi"], ba)
        elif ba:                                                    # "5 to 10 PM", "11 to 2 AM", "9-5 pm"
            end = _to_min(b["h"], b["mi"], ba)
            start = _to_min(a["h"], a["mi"], ba)
            if start > end and not (ba == "a" and a["h"] >= 7 and a["h"] != 12):
                start = _to_min(a["h"], a["mi"], "a" if ba == "p" else "p")
            elif start > end:
                start = _to_min(a["h"], a["mi"], "p")
            pen, note = 0.05, "start meridiem inferred from end"
        elif aa:                                                    # "9am-5"
            start = _to_min(a["h"], a["mi"], aa)
            end = pick_end(b, start)
            pen, note = 0.1, "end meridiem inferred"
        else:                                                       # "9-9", "5-10", "11-2": no AM/PM anywhere
            start = _to_min(a["h"], a["mi"], _guess_ap(a["h"]))
            end = pick_end(b, start)
            pen, note = 0.2, "no AM/PM in source, guessed from typical hours"
    if start is None or end is None or end > 1440:
        return None
    if end == 0 and start > 0:
        end = 1440
    if start == end:
        if start != 0:
            return None
        end = 1440
    return start, end, pen, note


def _parse_free_text(text: str) -> dict:
    """text -> {"days": {0..6: [(s,e),...]}, "penalty", "notes", "residual"}; days with [] are explicitly closed."""
    notes: list[str] = []
    t = _norm(text)
    if _HOLIDAY.search(t):
        t = _HOLIDAY.sub(" ", t)
        notes.append("holiday rules ignored (engine does not model PH)")
    t = re.sub(r"(?<=[A-Za-z]):", " ", t)                         # "Monday: 9 AM" -> "Monday  9 AM"
    pos, n = 0, len(t)
    groups: list[dict] = []
    pending: dict | None = None
    closed_next = False
    penalty, residual = 0.0, []
    prev_start: int | None = None

    def new_group(days, closed_pre=False):
        g = dict(days=set(days), ivs=[], closed=False, closed_pre=closed_pre, implicit=False, sealed=False)
        groups.append(g)
        return g

    def add_days(pend, days, closed_pre):
        if pend is not None and pend["implicit"] and pend["ivs"] and not pend["sealed"]:
            pend["days"], pend["implicit"], pend["sealed"] = set(days), False, True      # "7am-7pm Mon-Sat": days trail the times
            return pend
        if pend is None or pend["ivs"] or (pend["closed"] and not pend["closed_pre"]):
            pend = new_group(days, closed_pre)
        else:
            pend["days"] |= set(days); pend["last_added"] = set(days)
        if closed_pre:
            pend["closed"] = True
        return pend

    def add_range(pend, iv):
        if pend is not None and pend["closed"] and pend["closed_pre"] and pend.get("last_added"):
            # "Closed Sundays, Mon-Sat 10-6": the days added after the 'closed' belong to the times, not to the closed list
            pend["days"] -= pend["last_added"]
            g = new_group(pend["last_added"]); pend["last_added"] = None
            g["ivs"].append(iv)
            return g
        if pend is None or pend["sealed"] or (pend["closed"] and not pend["closed_pre"]):
            pend = new_group(range(7)); pend["implicit"] = True
        pend["ivs"].append(iv)
        return pend

    while pos < n:
        ch = t[pos]
        if ch in " \t\r\n,;/&()|•·.:[]+*'\"!":
            pos += 1
            continue
        m = _H24.match(t, pos)
        if m:
            pending = add_range(pending, (0, 1440)); pos = m.end(); continue
        m = _GROUPWORDS.match(t, pos)
        if m:
            w = m.group(0).lower()
            days = [5, 6] if w.startswith("weekend") else [0, 1, 2, 3, 4] if w.startswith("weekday") else list(range(7))
            pending = add_days(pending, days, closed_next)
            closed_next = False; pos = m.end(); continue
        m = _DAYRANGE.match(t, pos)
        if m and (pos == 0 or not t[pos - 1].isalpha()):
            def di(s):
                s = s.lower().rstrip("s") if s.lower() not in _DAYLOOKUP else s.lower()
                if s in _DAYLOOKUP: return _DAYLOOKUP[s]
                two = {"mo": 0, "tu": 1, "we": 2, "th": 3, "fr": 4, "sa": 5, "su": 6}
                return two.get(s[:2])
            d1 = di(m.group("d1")); d2 = di(m.group("d2")) if m.group("d2") else None
            if d1 is not None:
                days = [d1] if d2 is None else [(d1 + i) % 7 for i in range(((d2 - d1) % 7) + 1)]
                pending = add_days(pending, days, closed_next)
                closed_next = False; pos = m.end(); continue
        m = _RANGE.match(t, pos)
        if m:
            if not m.group("a") and re.match(rf"\s*-\s*{_TIME}", t[m.end():], re.I):
                pos += 1                                            # "Monday - 9am - 5pm": the first '-' is a separator
                continue
            a = _time(m.group("a")) if m.group("a") else None
            b = _time(m.group("b"))
            r = _resolve(a, b, prev_start)
            pos = m.end()
            if r is None:
                residual.append(m.group(0).strip()); continue
            s, e, pen, note = r
            penalty = max(penalty, pen)
            if note and note not in notes:
                notes.append(note)
            pending = add_range(pending, (s, e)); prev_start = s
            continue
        m = _CLOSED.match(t, pos)
        if m:
            if pending is not None and not pending["ivs"] and not pending["closed"]:
                pending["closed"] = True
            elif pending is None or pending["ivs"] or pending["closed"]:
                closed_next = True
            pos = m.end(); continue
        m = _WORD.match(t, pos)
        if m:
            w = m.group(0).lower()
            if w not in _FILLER and not w.isdigit():
                residual.append(m.group(0))
            pos = m.end(); continue
        if ch.isdigit():
            m = re.match(r"\d+(?::\d+)?", t[pos:]); residual.append(m.group(0)); pos += len(m.group(0)); continue
        residual.append(ch); pos += 1

    days: dict[int, list] = {}
    for g in groups:
        if g["closed"]:
            for d in g["days"]:
                days[d] = []
        elif g["ivs"]:
            for d in g["days"]:
                days[d] = list(g["ivs"])
    return dict(days=days, penalty=penalty, notes=notes, residual=residual)


# ====================================================================== intervals -> OSM string
def _hhmm(m: int) -> str:
    return f"{m // 60:02d}:{m % 60:02d}"


def _dayspec(days: list[int]) -> str:
    days = sorted(days)
    parts, i = [], 0
    while i < len(days):
        j = i
        while j + 1 < len(days) and days[j + 1] == days[j] + 1:
            j += 1
        if j - i >= 1:
            parts.append(f"{DAYS[days[i]]}-{DAYS[days[j]]}")
        else:
            parts.append(DAYS[days[i]])
        i = j + 1
    return ",".join(parts)


def intervals_to_osm(days: dict[int, list]) -> str | None:
    """{day: [(start, end)...]} (empty list = closed, absent = not listed) -> OSM opening_hours."""
    open_days = {d: sorted(set(iv)) for d, iv in days.items() if iv}
    if not open_days:
        return "off" if days else None
    if len(open_days) == 7 and all(iv == [(0, 1440)] for iv in open_days.values()):
        return "24/7"
    grouped: dict[tuple, list[int]] = {}
    for d in sorted(open_days):
        grouped.setdefault(tuple(open_days[d]), []).append(d)
    rules = []
    for ivs, ds in sorted(grouped.items(), key=lambda kv: kv[1][0]):
        spans = ",".join(f"{_hhmm(s)}-{_hhmm(e)}" for s, e in ivs)
        rules.append(f"{_dayspec(ds)} {spans}")
    closed = [d for d, iv in days.items() if not iv]
    if closed:
        rules.append(f"{_dayspec(closed)} off")
    return "; ".join(rules)


# ====================================================================== rules parser entry point
def parse_rules(text) -> dict:
    """Deterministic parser. `text` is raw source text (str)."""
    if text is None or not str(text).strip():
        return dict(opening_hours=None, confidence=0.0, notes="no source text", method="rules")
    text = str(text).strip()
    ok, _ = validate_osm_hours(text)
    if ok and text not in ("off", "closed"):
        return dict(opening_hours=text, confidence=0.95, notes="source already in OSM syntax", method="rules")
    if _NEVER.search(text) and not re.search(r"\d", text):
        return dict(opening_hours="off", confidence=0.85, notes="source says closed (permanently/temporarily)", method="rules")
    if _NOINFO.search(text) and not re.search(r"\d|24", text):
        return dict(opening_hours=None, confidence=0.0, notes="source has no usable hours (appointment/varies/call)", method="rules")
    p = _parse_free_text(text)
    days = p["days"]
    notes = list(p["notes"])
    if not any(days.values()) and not any(v == [] for v in days.values()):
        why = "no recognisable days/times" + (f" (unrecognised: {', '.join(p['residual'][:4])})" if p["residual"] else "")
        return dict(opening_hours=None, confidence=0.0, notes=why, method="rules")
    if not any(days.values()):
        return dict(opening_hours=None, confidence=0.0, notes="only 'closed' found, refusing to emit all-closed", method="rules")
    conf = 0.95 - p["penalty"]
    if p["residual"]:
        conf -= 0.25
        notes.append(f"unrecognised text: {', '.join(map(str, p['residual'][:5]))}")
    unlisted = [d for d in range(7) if d not in days]
    if unlisted:
        conf -= 0.1
        notes.append("not listed, treated as closed: " + ",".join(DAYS[d] for d in unlisted))
    osm = intervals_to_osm(days)
    ok, why = validate_osm_hours(osm)
    if not ok:
        return dict(opening_hours=None, confidence=0.0, notes=f"rejected: {why}", method="rules")
    return dict(opening_hours=osm, confidence=round(max(0.3, min(conf, 0.97)), 2), notes="; ".join(notes) or "ok", method="rules")


# ====================================================================== Claude parser
SYSTEM_PROMPT = """You convert messy business opening-hours text into OpenStreetMap opening_hours syntax for a walking-safety routing engine.

Return ONLY a JSON object, no prose, no code fences:
{"opening_hours": "<string or null>", "confidence": <0..1>, "notes": "<short>"}

The engine understands ONLY this subset:
- "24/7"
- rules separated by "; ", each rule = <days> <times>  (days optional = every day)
- days: Mo Tu We Th Fr Sa Su, ranges "Mo-Fr", lists "Mo,We", mixes "Mo-We,Fr"
- times: 24h "HH:MM-HH:MM" (two digits each), split shifts "11:00-14:00,17:00-22:00"
- overnight spans just run past midnight: "Fr,Sa 18:00-02:00" (end earlier than start). Midnight END is "24:00".
- closed days: "Su off"
Do NOT use: PH, SH, month names, "+", "sunrise/sunset", "open", comments in quotes, times above 24:00, or 12-hour times.

Hard rules:
- Use ONLY the supplied text. If the text gives no hours (empty, "by appointment", "hours vary", "call us", just a name) return {"opening_hours": null, "confidence": 0, "notes": "..."}. NEVER guess or fill in typical hours.
- If a day is not mentioned, omit it (the engine treats unlisted days as closed) and say so in notes.
- Ignore holiday clauses and say so in notes. "Permanently/temporarily closed" with no hours -> "off".
- If AM/PM is missing, pick the reading a normal business would have and lower confidence (<=0.7).
- Weekly schedule identical every day -> "Mo-Su HH:MM-HH:MM". All day every day -> "24/7".
- confidence: 0.95 clear and complete; 0.7-0.85 minor inference; <=0.5 ambiguous."""


def _extract_json(text: str) -> dict | None:
    text = text.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    try:
        return json.loads(text)
    except Exception:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                return None
    return None


def _cache_load() -> dict:
    try:
        return read_json(CLAUDE_CACHE)
    except Exception:
        return {}


_claude_client = None


def _client():
    global _claude_client
    if _claude_client is None:
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise SystemExit("ANTHROPIC_API_KEY is not set (export it or put it in services/hours/.env)")
        import anthropic
        _claude_client = anthropic.Anthropic(api_key=key)
    return _claude_client


def _claude_call(text: str, feedback: str | None = None) -> str:
    model = os.environ.get("HOURS_CLAUDE_MODEL", DEFAULT_MODEL)
    user = f"Opening hours text:\n<<<\n{text}\n>>>"
    if feedback:
        user += f"\n\nYour previous answer was rejected by the validator: {feedback}. Fix it and answer with the JSON object only."
    kw = dict(model=model, max_tokens=400, system=SYSTEM_PROMPT, messages=[{"role": "user", "content": user}])
    try:
        resp = _client().messages.create(temperature=0, **kw)
    except Exception as ex:
        if "temperature" in str(ex).lower():
            resp = _client().messages.create(**kw)
        else:
            raise
    return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")


def parse_claude(text, cache: dict | None = None) -> dict:
    if text is None or not str(text).strip():
        return dict(opening_hours=None, confidence=0.0, notes="no source text", method="claude")
    text = str(text).strip()
    model = os.environ.get("HOURS_CLAUDE_MODEL", DEFAULT_MODEL)
    key = hashlib.sha1(f"{model}\n{text}".encode()).hexdigest()
    if cache is not None and key in cache:
        return dict(cache[key], method="claude")
    feedback, result = None, None
    for attempt in range(2):
        raw = _claude_call(text, feedback)
        obj = _extract_json(raw)
        if not isinstance(obj, dict) or "opening_hours" not in obj:
            feedback = "not a JSON object with opening_hours/confidence/notes"
            continue
        oh = obj.get("opening_hours")
        try:
            conf = max(0.0, min(1.0, float(obj.get("confidence", 0))))
        except Exception:
            conf = 0.0
        if oh is None:
            result = dict(opening_hours=None, confidence=0.0, notes=str(obj.get("notes", ""))[:300]); break
        ok, why = validate_osm_hours(oh)
        if ok:
            result = dict(opening_hours=oh.strip(), confidence=round(conf, 2), notes=str(obj.get("notes", ""))[:300]); break
        feedback = why
    if result is None:
        result = dict(opening_hours=None, confidence=0.0, notes=f"claude output failed validation ({feedback})")
    if cache is not None:
        cache[key] = result
    return dict(result, method="claude")


# ====================================================================== dispatcher
class Parser:
    """parser: 'rules' (offline), 'claude' (always API), 'auto' (rules first, API only for low confidence)."""

    def __init__(self, mode: str = "rules", auto_threshold: float = 0.9):
        self.mode, self.threshold = mode, auto_threshold
        self.cache = _cache_load() if mode != "rules" else None
        self.api_calls = 0

    def save(self):
        if self.cache is not None:
            write_json(CLAUDE_CACHE, self.cache)

    def parse(self, text) -> dict:
        if text is None or not str(text).strip():
            return dict(opening_hours=None, confidence=0.0, notes="no source text", method="none")
        if self.mode == "rules":
            return parse_rules(text)
        if self.mode == "claude":
            return self._claude(text)
        r = parse_rules(text)
        if r["opening_hours"] is not None and r["confidence"] >= self.threshold:
            return r
        c = self._claude(text)
        if c["opening_hours"] is None and r["opening_hours"] is not None:
            return dict(r, notes=r["notes"] + "; claude returned null")     # keep the validated rule parse
        return c

    def _claude(self, text):
        before = len(self.cache)
        out = parse_claude(text, self.cache)
        self.api_calls += int(len(self.cache) > before)
        return out


# ====================================================================== stage: matches -> evidence
def source_label(parsed_method: str, mock: bool) -> str:
    base = "claude:parsed" if parsed_method == "claude" else "apify:google_maps"
    return f"mock:{base}" if mock else base


def run(matches_path: Path, out_path: Path, parser_mode: str, mock: bool, only_missing: bool = False) -> dict:
    matches = read_json(matches_path)["matches"]
    parser = Parser(parser_mode)
    evidence, parsed_rows = {}, []
    stats = dict(matched=len(matches), parsed_ok=0, null=0, no_source_text=0, closed_off=0, claude_calls=0, fills_missing_osm=0)
    for m in matches:
        text = m.get("source_text")
        r = parser.parse(text)
        row = dict(osm_id=m["osm_id"], source_text=text, **{k: r[k] for k in ("opening_hours", "confidence", "notes", "method")})
        parsed_rows.append(row)
        if not text or not str(text).strip():
            stats["no_source_text"] += 1
        if r["opening_hours"] is None:
            stats["null"] += 1
            continue
        if only_missing and m.get("osm_hours"):
            continue
        stats["parsed_ok"] += 1
        stats["closed_off"] += r["opening_hours"] == "off"
        stats["fills_missing_osm"] += not m.get("osm_hours")
        conf = r["confidence"] * (0.8 + 0.2 * m["confidence"])
        evidence[m["osm_id"]] = dict(opening_hours=r["opening_hours"], confidence=round(conf, 2),
                                     source=source_label(r["method"], mock), fetched_at=m.get("fetched_at") or now_iso(),
                                     raw=text, matched_name=m.get("g_title"), distance_m=round(m["distance_m"], 1))
    parser.save()
    stats["claude_calls"] = parser.api_calls
    write_json(out_path, evidence)
    write_json(HERE.parent.parent / "data" / "cache" / f"hours_parsed_{suffix(mock)}.json",
               dict(generated_at=now_iso(), parser=parser_mode, rows=parsed_rows), indent=None)
    stats["evidence_entries"] = len(evidence)
    return stats


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mock", action="store_true", help="offline: read mock matches, use rules parser, write *.mock.json")
    ap.add_argument("--parser", choices=["rules", "claude", "auto"], help="default: rules with --mock, auto otherwise")
    ap.add_argument("--matches", type=Path)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--only-missing", action="store_true", help="only emit evidence for places with no OSM opening_hours")
    a = ap.parse_args(argv)
    mode = a.parser or ("rules" if a.mock else "auto")
    matches = a.matches or CACHE / f"hours_matches_{suffix(a.mock)}.json"
    out = a.out or CACHE / ("hours_evidence.mock.json" if a.mock else "hours_evidence.json")
    stats = run(matches, out, mode, a.mock, a.only_missing)
    print(json.dumps(dict(stage="parse", parser=mode, out=str(out), **stats)))
    return stats


if __name__ == "__main__":
    main()
