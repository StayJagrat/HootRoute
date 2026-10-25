"""Shared plumbing: env, agent construction, addresses, engine client, small helpers."""
from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path

import httpx
from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
load_dotenv(HERE / ".env")

ENGINE_URL = os.environ.get("ENGINE_URL", "http://localhost:8000").rstrip("/")
OUT_DIR = Path(os.environ.get("OUT_DIR", str(HERE / "out"))).resolve()
BUREAU_PORT = int(os.environ.get("BUREAU_PORT", "8100"))
LOG = logging.getLogger("hootroute")

# Fixed ports / seed variable names for the core agents. Place agents come from demo_places.json.
CORE = {
    "head":    dict(name="hootroute-head",    seed_env="HEAD_SEED",    port=8001),   # ASI:One front door (Agent Chat Protocol)
    "guide":   dict(name="hootroute-guide",   seed_env="GUIDE_SEED",   port=8002),
    "checker": dict(name="hootroute-checker", seed_env="CHECKER_SEED", port=8003),
    "rescuer": dict(name="hootroute-rescuer", seed_env="RESCUER_SEED", port=8004),
}


def mode() -> str:
    return os.environ.get("STREETWISE_MODE", "mailbox").lower()


def seed_for(seed_env: str) -> str:
    """Seeds come from env only. STREETWISE_ALLOW_DEV_SEEDS=1 (set by test_local.py) derives throwaway seeds for offline tests."""
    v = os.environ.get(seed_env, "").strip()
    if v:
        return v
    if os.environ.get("STREETWISE_ALLOW_DEV_SEEDS") == "1":
        return f"streetwise-offline-test-only-{seed_env.lower()}"
    raise RuntimeError(f"{seed_env} is not set. Copy .env.example to .env and set a stable seed (python -c \"import secrets; print(secrets.token_hex(24))\").")


def address_from_seed(seed: str) -> str:
    from uagents_core.identity import Identity
    return Identity.from_seed(seed, 0).address


def load_places() -> list[dict]:
    """Simulated shop agents retired with the old chat layer (legacy_chat/); kept so old imports keep working."""
    return []


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def place_cfg_by_id(place_id: str) -> dict | None:
    return next((p for p in load_places() if p["place_id"] == place_id), None)


def address_of(key: str) -> str:
    """Address of a core agent (key in CORE) or a place agent (key 'place:<place_id>'). <SEED_ENV prefix>_ADDRESS overrides the derived value."""
    if key.startswith("place:"):
        cfg = place_cfg_by_id(key.split(":", 1)[1]); seed_env = cfg["seed_env"]
    else:
        seed_env = CORE[key]["seed_env"]
    override = os.environ.get(seed_env.replace("_SEED", "_ADDRESS"), "").strip()
    return override or address_from_seed(seed_for(seed_env))


def make_agent(name: str, seed_env: str, port: int, readme: str):
    """One construction path for every agent so mailbox/local behaviour is identical everywhere."""
    from uagents import Agent
    seed = seed_for(seed_env)
    if mode() == "local":
        return Agent(name=name, seed=seed, port=port, endpoint=[f"http://127.0.0.1:{port}/submit"], publish_agent_details=False,
                     enable_agent_inspector=False, log_level=logging.INFO)
    return Agent(name=name, seed=seed, port=port, mailbox=True, publish_agent_details=True,
                 readme_path=str(HERE / "readmes" / readme), description=None)


# ---------------------------------------------------------------------------------------------------------------
class Engine:
    """Thin async client for the Streetwise FastAPI engine. Agents decide when to call it; they never compute the score."""

    def __init__(self, base: str | None = None, timeout: float = 60.0):
        self.base = (base or ENGINE_URL).rstrip("/"); self.timeout = timeout

    async def _req(self, method: str, path: str, **kw):
        async with httpx.AsyncClient(timeout=self.timeout) as c:
            r = await c.request(method, self.base + path, **kw); r.raise_for_status(); return r.json()

    async def landmarks(self): return await self._req("GET", "/api/landmarks")
    async def places(self, session="demo", day=4, minute=1370): return await self._req("GET", "/api/places", params=dict(session=session, day=day, minute=minute))
    async def route(self, session, o, d, day, minute):
        return await self._req("POST", "/api/route", json=dict(session=session, origin=dict(lat=o[0], lon=o[1]), dest=dict(lat=d[0], lon=d[1]), day=day, minute=minute))
    async def suggest(self, session): return await self._req("POST", "/api/agents/place/suggest", json=dict(session=session))
    async def declare(self, session, place_id, until, day, minute):
        return await self._req("POST", "/api/agents/place/declare", json=dict(session=session, place_id=place_id, until_minute=until, day=day, minute=minute))
    async def audit(self, session="auditor"): return await self._req("POST", "/api/agents/auditor/run", json=dict(session=session))
    async def reset(self, session): return await self._req("POST", "/api/session/reset", json=dict(session=session))


def fmt_minute(m: float) -> str:
    m = int(round(m)) % 1440; h, mm = divmod(m, 60)
    return f"{(h % 12) or 12}:{mm:02d} {'AM' if h < 12 else 'PM'}"


DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def local_bureau_policy():
    """Local/offline mode: never touch the Almanac or Agentverse (used by test_local.py and STREETWISE_MODE=local)."""
    from uagents_core.registration import BatchRegistrationPolicy

    class NoopBatch(BatchRegistrationPolicy):
        async def register(self): return None
        def add_agent(self, agent_info, identity): return None
    return NoopBatch()
