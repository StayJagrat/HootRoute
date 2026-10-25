"""AGENT_RUNTIME=uagents: the agents run as registered uAgents in services/agents/live_bureau.py, not in this process.

RemoteRuntime has the same surface the gateway uses on the in-process Runtime; it forwards over HTTP to the bureau's bridge.
The agents answer through POST /api/internal/publish.
"""
from __future__ import annotations

import asyncio
import logging

import httpx

log = logging.getLogger("hootroute.bridge")


class RemoteRuntime:
    walks: dict = {}                     # walk state lives in the bureau

    def __init__(self, url: str, secret: str):
        self.url, self.secret = url, secret; self.client = httpx.AsyncClient(timeout=30); self.lock = asyncio.Lock()

    async def _post(self, kind: str, body: dict):
        try:
            r = await self.client.post(f"{self.url}/{kind}", json=body, headers={"X-Bridge-Secret": self.secret})
            r.raise_for_status(); return r.json()
        except httpx.HTTPError as e:
            log.error("agent bureau unreachable for %s: %s", kind, type(e).__name__); return None

    async def request(self, record: dict, guardian_url: str, cached=None):
        rec = {k: v for k, v in record.items() if k != "walker_token"}       # the bureau never needs the walker's token
        await self._post("request", {"record": rec, "guardianUrl": guardian_url, "cached": list(cached) if cached else None})

    async def handle(self, env: dict):
        async with self.lock: await self._post("envelope", {"envelope": env})     # keep position order

    async def place_update(self, place_id: str, decl: dict, walks: list[str]):
        await self._post("place", {"placeId": place_id, "declaration": decl, "walks": walks})

    async def set_declarations(self, declared: dict):
        await self._post("declarations", {"declared": {str(k): v for k, v in declared.items()}})

    async def audit(self, day: int, minute: int) -> dict:
        return await self._post("audit", {"day": day, "minute": minute}) or {"type": "audit.result", "ranking": [], "draft311": "DRAFT — not submitted. The audit agent did not answer."}

    async def set_sharing(self, walk_id: str, active: bool, guardian_url: str | None):
        await self._post("share", {"walkId": walk_id, "active": active, "guardianUrl": guardian_url})

    def status(self, walk_id: str): return None
    def restore(self, *a, **k): return None
    def start(self): pass
    async def stop(self): await self.client.aclose()
