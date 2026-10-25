"""Guardrails around Professor Hoot, enforced in code (the system prompt repeats them, but nothing here depends on the model).

Input
- Personal identifiers (SSN, card numbers, emails, phone numbers) are redacted before the text reaches Claude or any log.
- An emergency ("someone is following me", "call 911") gets an immediate fixed answer: call 911 yourself, here is what to
  say. No model in that path, no delay, and HootRoute never claims to have called anyone.
- Text is capped at 1000 characters.

Output
- Banned words are replaced (conditions, not a safety rating) — see head_brain.clean.
- Markdown is flattened to plain sentences (the UI and the voice read plain text).
- Claims that HootRoute or an agent called 911, the police or anyone else are removed.
- An answer with no tool calls that isn't about a journey is replaced with a short scope reminder.
- Every number must come from a tool result — see head_brain.numbers_check.
"""
from __future__ import annotations

import re

PII = [
    ("ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("card", re.compile(r"\b(?:\d[ -]?){13,19}\b")),
    ("email", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")),
    ("phone", re.compile(r"(?<!\d)(?:\+?1[ .-]?)?\(?\d{3}\)?[ .-]?\d{3}[ .-]?\d{4}(?!\d)")),
]
EMERGENCY = re.compile(
    r"\b(call (911|the police|an ambulance)|(being|is|someone('s)?|somebody('s)?) (following|chasing|attacking|hurting) me|i('m| am) (being )?(followed|attacked|chased|hurt|injured|bleeding)"
    r"|(help|save) me( now)?\b.*\b(now|please|urgent)|(this is|it'?s|i have|having) an emergency|i('m| am) in danger|threaten(ed|ing) me)\b", re.I)
JOURNEY = re.compile(r"\b(walk|walking|route|routes|go|going|get to|head(ing)? to|from|to|leav(e|ing)|bart|muni|station|street|st\b|ave|park|home|shift|library|class|bike|cycl|wheelchair|step.free|tonight|pm|am|open|check|hours|block|detour|avoid|closed|construction)\b", re.I)
CONTACT_CLAIM = re.compile(r"[^.!?]*\b(I|we|HootRoute|Wally|Hoot|the app)\b[^.!?]*\b(called|have called|am calling|contacted|alerted|notified|dispatched)\b[^.!?]*\b(911|police|emergency|ambulance|authorities)\b[^.!?]*[.!?]?", re.I)
MAX_IN = 1000
MAX_OUT = 1400

EMERGENCY_ANSWER = ("If you are in danger, call 911 now: tap Call 911 or dial it yourself. HootRoute can't call for you. "
                    "Tell the dispatcher the street you're on and the nearest cross street, then keep moving toward somewhere lit and listed open if you can. "
                    "When you're ready, I can plan a route to the nearest open place or BART station.")
SCOPE_ANSWER = ("I can only help with journeys in San Francisco: planning a walk, bike ride or step-free route, checking which places are listed open "
                "on the way, and finding another way if something's blocked. Where are you starting from, and where are you headed?")


def redact(text: str) -> tuple[str, list[str]]:
    found = []
    for kind, rx in PII:
        if rx.search(text):
            found.append(kind); text = rx.sub(f"[{kind} removed]", text)
    return text[:MAX_IN], found


def is_emergency(text: str) -> bool: return bool(EMERGENCY.search(text))


def flatten_markdown(text: str) -> str:
    text = re.sub(r"\*\*(.+?)\*\*|__(.+?)__", lambda m: m.group(1) or m.group(2), text)
    text = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", text)
    text = re.sub(r"(?m)^\s*[-*•]\s+", "", text)
    text = re.sub(r"(?m)^\s*\d+\.\s+", "", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def sanitize(answer: str) -> tuple[str, list[str]]:
    """Plain text, no claims of contacting anyone, bounded length. Returns (text, what was changed)."""
    changed = []
    flat = flatten_markdown(answer)
    if flat != answer.strip(): changed.append("markdown")
    cut = CONTACT_CLAIM.sub("", flat)
    if cut != flat: changed.append("contact claim"); flat = cut.strip() + " HootRoute never calls 911 or anyone else for you."
    if len(flat) > MAX_OUT:
        flat = flat[:MAX_OUT].rsplit(".", 1)[0] + "."; changed.append("length")
    return flat, changed


def off_topic(request: str, used_tools: int, answer: str) -> bool:
    """No tool ran, the request names no journey, and the answer isn't about one either."""
    return used_tools == 0 and not JOURNEY.search(request) and not JOURNEY.search(answer[:400])
