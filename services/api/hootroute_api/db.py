"""SQLite persistence: walks, the envelope history of every room, GPS traces, alerts, shopkeeper declarations and audits.

One file, WAL mode, one connection behind a lock. Every statement is a few rows, so calls run inline on the event loop.
Swap for Postgres by reimplementing this module; nothing else touches SQL.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS walks (
  id TEXT PRIMARY KEY, created_at REAL NOT NULL, status TEXT NOT NULL, walker_token TEXT NOT NULL,
  walker_name TEXT NOT NULL, guardian_name TEXT NOT NULL, guardian_phone TEXT,
  origin TEXT NOT NULL, destination TEXT NOT NULL, depart_day INTEGER NOT NULL, depart_minute INTEGER NOT NULL,
  choice TEXT NOT NULL, thresholds TEXT NOT NULL, replay INTEGER NOT NULL DEFAULT 0, time_scale REAL NOT NULL DEFAULT 1,
  started_at REAL, ended_at REAL, outcome TEXT, summary TEXT
);
CREATE TABLE IF NOT EXISTS envelopes (walk_id TEXT NOT NULL, id TEXT NOT NULL, ts REAL NOT NULL, type TEXT NOT NULL, body TEXT NOT NULL, PRIMARY KEY (walk_id, id));
CREATE INDEX IF NOT EXISTS envelopes_walk_ts ON envelopes(walk_id, ts);
CREATE TABLE IF NOT EXISTS positions (walk_id TEXT NOT NULL, ts REAL NOT NULL, lng REAL NOT NULL, lat REAL NOT NULL, speed REAL, accuracy REAL, replay INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS positions_walk_ts ON positions(walk_id, ts);
CREATE TABLE IF NOT EXISTS alerts (walk_id TEXT NOT NULL, ts REAL NOT NULL, reason TEXT NOT NULL, lng REAL, lat REAL, place TEXT, sms TEXT, acked_by TEXT, acked_at REAL);
CREATE TABLE IF NOT EXISTS declarations (
  place_id TEXT PRIMARY KEY, day INTEGER NOT NULL, until_minute INTEGER, open_until TEXT NOT NULL,
  safe_haven INTEGER NOT NULL, front_light INTEGER NOT NULL, updated_at REAL NOT NULL, expires_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS audits (ts REAL NOT NULL, body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS routes (walk_id TEXT PRIMARY KEY, body TEXT NOT NULL, updated_at REAL NOT NULL);
"""

WALK_COLUMNS = ("id", "created_at", "status", "walker_token", "walker_name", "guardian_name", "guardian_phone", "origin", "destination", "depart_day",
                "depart_minute", "choice", "thresholds", "replay", "time_scale", "started_at", "ended_at", "outcome", "summary", "backup_name", "backup_phone", "guardian_token", "notify_consent", "sharing", "travel_mode", "travel_options")
JSON_COLUMNS = {"origin", "destination", "thresholds", "travel_options"}


class DB:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row; self.lock = threading.Lock()
        with self.lock:
            self.conn.execute("PRAGMA journal_mode=WAL"); self.conn.execute("PRAGMA synchronous=NORMAL"); self.conn.executescript(SCHEMA)
            cols = {r[1] for r in self.conn.execute("PRAGMA table_info(walks)")}
            for c, kind in (("backup_name", "TEXT"), ("backup_phone", "TEXT"),          # older databases get newer columns here
                            ("guardian_token", "TEXT"), ("notify_consent", "INTEGER NOT NULL DEFAULT 0"), ("sharing", "INTEGER NOT NULL DEFAULT 1"),
                            ("travel_mode", "TEXT NOT NULL DEFAULT 'walk'"), ("travel_options", "TEXT NOT NULL DEFAULT '{}'")):
                if c not in cols: self.conn.execute(f"ALTER TABLE walks ADD COLUMN {c} {kind}")

    def _exec(self, sql: str, args=()):
        with self.lock: return self.conn.execute(sql, args)

    def _all(self, sql: str, args=()):
        with self.lock: return self.conn.execute(sql, args).fetchall()

    # ---------- walks ----------
    def create_walk(self, walk: dict):
        walk = {"travel_mode": "walk", "travel_options": {}, **walk}
        row = {k: (json.dumps(walk[k]) if k in JSON_COLUMNS else walk.get(k)) for k in WALK_COLUMNS}
        self._exec(f"INSERT INTO walks ({','.join(WALK_COLUMNS)}) VALUES ({','.join('?' * len(WALK_COLUMNS))})", tuple(row[k] for k in WALK_COLUMNS))

    @staticmethod
    def _walk(row) -> dict | None:
        if row is None: return None
        d = dict(row)
        for k in JSON_COLUMNS: d[k] = json.loads(d[k])
        for k in ("replay", "notify_consent", "sharing"): d[k] = bool(d.get(k))
        return d

    def walk(self, walk_id: str) -> dict | None:
        rows = self._all("SELECT * FROM walks WHERE id = ?", (walk_id,)); return self._walk(rows[0] if rows else None)

    def walks(self, active_only=False, limit=20) -> list[dict]:
        sql = "SELECT * FROM walks" + (" WHERE status NOT IN ('ended')" if active_only else "") + " ORDER BY created_at DESC LIMIT ?"
        return [self._walk(r) for r in self._all(sql, (limit,))]

    def update_walk(self, walk_id: str, **fields):
        if not fields: return
        cols = ", ".join(f"{k} = ?" for k in fields)
        self._exec(f"UPDATE walks SET {cols} WHERE id = ?", (*[json.dumps(v) if k in JSON_COLUMNS else v for k, v in fields.items()], walk_id))

    # ---------- room history ----------
    def add_envelope(self, env: dict):
        self._exec("INSERT OR IGNORE INTO envelopes (walk_id, id, ts, type, body) VALUES (?, ?, ?, ?, ?)",
                   (env["walkId"], env["id"], env["ts"], env["msg"]["type"], json.dumps(env, separators=(",", ":"))))

    def envelopes(self, walk_id: str, limit=400) -> list[dict]:
        rows = self._all("SELECT body FROM (SELECT body, ts FROM envelopes WHERE walk_id = ? ORDER BY ts DESC LIMIT ?) ORDER BY ts", (walk_id, limit))
        return [json.loads(r["body"]) for r in rows]

    def add_position(self, walk_id: str, ts: float, lng: float, lat: float, speed: float | None, accuracy: float | None, replay: bool):
        self._exec("INSERT INTO positions VALUES (?, ?, ?, ?, ?, ?, ?)", (walk_id, ts, lng, lat, speed, accuracy, int(replay)))

    def purge_positions(self, older_than_s: float) -> int:
        cut = time.time() - older_than_s
        return self._exec("DELETE FROM positions WHERE walk_id IN (SELECT id FROM walks WHERE status = 'ended' AND ended_at < ?)", (cut,)).rowcount

    # ---------- alerts ----------
    def add_alert(self, walk_id: str, reason: str, lng_lat, place: str):
        self._exec("INSERT INTO alerts (walk_id, ts, reason, lng, lat, place) VALUES (?, ?, ?, ?, ?, ?)", (walk_id, time.time(), reason, lng_lat[0], lng_lat[1], place))

    def ack_alert(self, walk_id: str, by: str):
        self._exec("UPDATE alerts SET acked_by = ?, acked_at = ? WHERE walk_id = ? AND acked_by IS NULL", (by, time.time(), walk_id))

    # ---------- shopkeeper declarations ----------
    def set_declaration(self, place_id: str, day: int, until_minute: int | None, open_until: str, safe_haven: bool, front_light: bool, expires_at: float):
        self._exec("INSERT OR REPLACE INTO declarations VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                   (place_id, day, until_minute, open_until, int(safe_haven), int(front_light), time.time(), expires_at))

    def declarations(self) -> list[dict]:
        return [dict(r) for r in self._all("SELECT * FROM declarations WHERE expires_at > ?", (time.time(),))]

    def declaration(self, place_id: str) -> dict | None:
        rows = self._all("SELECT * FROM declarations WHERE place_id = ? AND expires_at > ?", (place_id, time.time())); return dict(rows[0]) if rows else None

    # ---------- engine routes behind the latest plan (lets the agents resume a walk after a restart) ----------
    def set_routes(self, walk_id: str, routes: dict):
        self._exec("INSERT OR REPLACE INTO routes VALUES (?, ?, ?)", (walk_id, json.dumps(routes, separators=(",", ":")), time.time()))

    def routes(self, walk_id: str) -> dict | None:
        rows = self._all("SELECT body FROM routes WHERE walk_id = ?", (walk_id,)); return json.loads(rows[0]["body"]) if rows else None

    # ---------- audits ----------
    def add_audit(self, body: dict): self._exec("INSERT INTO audits VALUES (?, ?)", (time.time(), json.dumps(body)))

    def latest_audit(self) -> dict | None:
        rows = self._all("SELECT ts, body FROM audits ORDER BY ts DESC LIMIT 1"); return {"ts": rows[0]["ts"], **json.loads(rows[0]["body"])} if rows else None
