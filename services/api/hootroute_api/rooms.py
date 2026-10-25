"""Walk rooms: one per walk. The hub relays envelopes, keeps history for late joiners and persists it. It holds no walk logic.

Agents and side effects subscribe with `observe()`; they see every envelope after it has been delivered.
"""
from __future__ import annotations

import asyncio
import logging
from collections import deque
from collections.abc import Awaitable, Callable

from fastapi import WebSocket

from .contract import LATEST_ONLY
from .db import DB

log = logging.getLogger("hootroute.rooms")
Observer = Callable[[dict], Awaitable[None]]
HISTORY = 400


class Room:
    def __init__(self, walk_id: str, history: list[dict] | None = None, persistent: bool = True):
        self.walk_id = walk_id; self.persistent = persistent
        self.clients: dict[WebSocket, str] = {}
        self.history: deque[dict] = deque(history or [], maxlen=HISTORY)
        self.lock = asyncio.Lock()
        self.ended = any(e["msg"].get("type") == "walk.end" for e in self.history)

    def _remember(self, env: dict):
        kind = env["msg"].get("type")
        if kind == "walk.reset":
            self.history = deque((e for e in self.history if e["msg"].get("type") in ("place.update", "guardian.join")), maxlen=HISTORY)
        elif kind in LATEST_ONLY:
            self.history = deque((e for e in self.history if e["msg"].get("type") != kind), maxlen=HISTORY)
        if kind == "walk.end":       # location sharing stops when the walk ends: late joiners never see the trace
            self.ended = True
            self.history = deque((e for e in self.history if e["msg"].get("type") != "walk.position"), maxlen=HISTORY)
        self.history.append(env)


class Hub:
    def __init__(self, db: DB):
        self.db = db; self.rooms: dict[str, Room] = {}; self.observers: list[Observer] = []

    def observe(self, fn: Observer): self.observers.append(fn)

    def room(self, walk_id: str, persistent: bool) -> Room:
        r = self.rooms.get(walk_id)
        if r is None:
            r = Room(walk_id, self.db.envelopes(walk_id, HISTORY) if persistent else [], persistent); self.rooms[walk_id] = r
        return r

    async def join(self, walk_id: str, sock: WebSocket, role: str, persistent: bool) -> Room:
        r = self.room(walk_id, persistent)
        async with r.lock:
            await sock.send_json({"kind": "history", "envelopes": list(r.history)})
            r.clients[sock] = role
        return r

    async def leave(self, walk_id: str, sock: WebSocket):
        r = self.rooms.get(walk_id)
        if not r: return
        async with r.lock: r.clients.pop(sock, None)
        if not r.clients and not r.persistent: self.rooms.pop(walk_id, None)

    async def publish(self, env: dict, exclude: WebSocket | None = None, observe: bool = True):
        r = self.rooms.get(env["walkId"]) or self.room(env["walkId"], persistent=self.db.walk(env["walkId"]) is not None)
        async with r.lock:
            if r.ended and r.persistent and env["msg"].get("type") == "walk.position": return
            r._remember(env)
            if r.persistent and env["msg"].get("type") != "walk.position": self.db.add_envelope(env)
            dead = []
            for peer in list(r.clients):
                if peer is exclude: continue
                try: await peer.send_json(env)
                except Exception: dead.append(peer)
            for peer in dead: r.clients.pop(peer, None)
        if observe:
            for fn in self.observers:
                try: await fn(env)
                except Exception: log.exception("observer failed on %s", env["msg"].get("type"))

    async def kick(self, walk_id: str, role: str, code: int = 4401):
        """Disconnect every client of one role (sharing stopped: guardians lose the live view immediately)."""
        r = self.rooms.get(walk_id)
        if not r: return
        async with r.lock:
            out = [s for s, rl in r.clients.items() if rl == role]
            for s in out: r.clients.pop(s, None)
        for s in out:
            try: await s.close(code=code)
            except Exception: pass

    def active_room_ids(self) -> list[str]: return [k for k, r in self.rooms.items() if r.persistent]
