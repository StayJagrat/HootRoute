"""Abuse limits and log hygiene for a public gateway.

- Per-client token buckets on planning and on every endpoint that can spend money (Claude, Apify, Mapillary, Cartesia).
- A daily cap on paid hours checks for the whole gateway.
- Access-log redaction: walker, guardian and admin tokens travel in WebSocket query strings, and uvicorn logs the full
  request line. The filter rewrites them to *** before the line is written.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import HTTPException, Request

SF = ZoneInfo("America/Los_Angeles")

# (requests, per seconds) for each bucket
LIMITS: dict[str, tuple[int, float]] = {
    "head": (12, 60), "check": (4, 60), "vision": (10, 60), "tts": (30, 60), "plan": (30, 60), "walk": (10, 60), "shop": (10, 60),
}


class RateLimiter:
    def __init__(self, limits: dict[str, tuple[int, float]] | None = None, enabled: bool = True):
        self.limits = limits or LIMITS; self.enabled = enabled; self.lock = threading.Lock()
        self.buckets: dict[tuple[str, str], tuple[float, float]] = {}      # (bucket, client) -> (tokens, last refill)

    def take(self, bucket: str, client: str) -> float:
        """0.0 when allowed, otherwise seconds until the next request would be."""
        if not self.enabled: return 0.0
        cap, per = self.limits[bucket]; rate = cap / per; now = time.monotonic()
        with self.lock:
            if len(self.buckets) > 20_000: self.buckets = {k: v for k, v in self.buckets.items() if now - v[1] < 600}
            tokens, last = self.buckets.get((bucket, client), (float(cap), now))
            tokens = min(cap, tokens + (now - last) * rate)
            if tokens < 1: self.buckets[(bucket, client)] = (tokens, now); return (1 - tokens) / rate
            self.buckets[(bucket, client)] = (tokens - 1, now); return 0.0


def client_id(request: Request) -> str:
    """The caller's address. Behind Caddy, uvicorn --proxy-headers already resolves X-Forwarded-For into request.client."""
    return request.client.host if request.client else "unknown"


def limit(request: Request, bucket: str):
    lim: RateLimiter | None = getattr(request.app.state, "limiter", None)
    if lim is None: return
    wait = lim.take(bucket, client_id(request))
    if wait: raise HTTPException(429, "Too many requests. Wait a moment and try again.", headers={"Retry-After": str(max(1, round(wait)))})


class DailyBudget:
    """Counts paid provider runs per San Francisco calendar day."""
    def __init__(self, per_day: int):
        self.per_day = per_day; self.day = ""; self.used = 0; self.lock = threading.Lock()

    def _roll(self):
        today = datetime.now(SF).strftime("%Y-%m-%d")
        if today != self.day: self.day, self.used = today, 0

    def remaining(self) -> int:
        with self.lock: self._roll(); return max(0, self.per_day - self.used)

    def spend(self) -> bool:
        with self.lock:
            self._roll()
            if self.used >= self.per_day: return False
            self.used += 1; return True


SECRET_QS = re.compile(r"((?:token|g|admin|walkerToken)=)[^&\s\"]+")


def redact(text: str) -> str: return SECRET_QS.sub(r"\1***", text)


class RedactTokens(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple) and record.args:
            record.args = tuple(redact(a) if isinstance(a, str) else a for a in record.args)
        elif isinstance(record.msg, str):
            record.msg = redact(record.msg)
        return True


def install_log_redaction():
    for name in ("uvicorn.access", "uvicorn.error", "uvicorn"):
        lg = logging.getLogger(name)
        if not any(isinstance(f, RedactTokens) for f in lg.filters): lg.addFilter(RedactTokens())
