"""The agents' only door into the deterministic engine. Every call runs off the event loop; the engine serialises itself with its own lock.

Agents decide when to call it and what to say about the answer. They never compute or change a score.
"""
from __future__ import annotations

import asyncio
import uuid

from hootroute_engine.engine import Engine
from hootroute_engine.world import DAYS

from .plan_data import _fixed_route_stats, build_plan


class EnginePort:
    def __init__(self, engine: Engine):
        self.engine = engine

    async def _run(self, fn, *args, **kw): return await asyncio.to_thread(fn, *args, **kw)

    async def plan(self, origin: dict, dest: dict, day: int, minute: int, walker: str, guardian: str, avoid: list | None = None, limits: dict | None = None) -> tuple[dict, dict]:
        """(DemoData, {'best', 'fast'[, 'balanced']} engine routes). Raises ValueError with a walker-readable message when the points cannot be routed.
        `avoid` = [(lat, lon, radius_m)] for reported obstacles."""
        return await self._run(build_plan, self.engine, dest["lat"], dest["lon"], dest.get("name") or "Destination", (origin["lat"], origin["lon"]),
                               origin.get("name") or "Start", day, minute, walker, guardian, f"plan:{uuid.uuid4().hex[:8]}", False, avoid, limits)

    async def rescore(self, routes: dict, day: int, minute: int) -> dict:
        def run():
            with self.engine.lock:
                ctx = self.engine.ctx("_rescore", day, minute)
                return {"hootroute": _fixed_route_stats(self.engine, routes["best"], ctx), "shortest": _fixed_route_stats(self.engine, routes["fast"], ctx)}
        return await self._run(run)

    async def where(self, lng_lat) -> str:
        return (await self._run(self.engine.where, lng_lat[1], lng_lat[0]))["text"]

    async def decide(self, route: dict, meters: float) -> dict:
        """The engine's stop rule at this point of the route: 'quiet' near a listed open place, else 'checkin'."""
        return await self._run(self.engine.watcher_decide, route, meters, None, 90, None, False)

    async def darkness_debt(self, day: int, minute: int, near_coords=None, top=5) -> dict:
        near = self.engine.center_of(near_coords) if near_coords else None
        return await self._run(self.engine.darkness_debt, day, minute, 1200, top, near)

    async def cases_on_street(self, street: str, limit=3) -> list[dict]: return await self._run(self.engine.cases_on_street, street, 30.0, limit)

    async def cases_near(self, coords, radius=40.0, limit=5) -> list[dict]: return await self._run(self.engine.cases_near, coords, radius, limit)

    def place(self, place_id: str) -> dict | None:
        W = self.engine.W; i = W.place_index.get(place_id)
        return W.places[i] if i is not None else None

    def set_declarations(self, declared: dict[int, dict[str, int]]): self.engine.set_declarations(declared)

    @staticmethod
    def day_name(day: int) -> str: return DAYS[day % 7]
