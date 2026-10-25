"""Per-walk state the four agents share inside one runtime. Rebuilt from the walk record and room history after a restart."""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from hootroute_engine import geo
from hootroute_engine.mobility import travel_profile

DEFAULT_THRESHOLDS = {"stopSeconds": 90, "replySeconds": 45, "escalateSeconds": 90}
LIMITS = {"stopSeconds": (20, 600), "replySeconds": (10, 300), "escalateSeconds": (20, 900)}


def effective_thresholds(raw: dict | None, replay: bool, time_scale: float) -> dict:
    """Walker's standing orders, clamped. A labelled GPS replay runs faster than real time, so its timers shrink by the same factor."""
    out = {}
    for k, d in DEFAULT_THRESHOLDS.items():
        v = (raw or {}).get(k, d)
        lo, hi = LIMITS[k]; v = min(hi, max(lo, float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else d))
        out[k] = v / max(1.0, time_scale) if replay else v
    return out


@dataclass
class Walk:
    id: str
    walker: str
    guardian: str
    guardian_phone: str | None
    guardian_url: str
    origin: dict                    # {lat, lon, name}
    dest: dict
    day: int
    minute: int
    travel_mode: str = "walk"
    travel_options: dict = field(default_factory=dict)
    choice: str = "hootroute"
    replay: bool = False
    time_scale: float = 1.0
    thresholds: dict = field(default_factory=lambda: dict(DEFAULT_THRESHOLDS))
    backup_name: str | None = None   # optional second trusted contact (ladder step 3)
    backup_phone: str | None = None
    notify_consent: bool = False     # walker opted in to SMS / calls to their contacts
    sharing: bool = True             # live link active; off = guardian link revoked, no SMS or calls
    notifications: int = 0           # SMS + calls sent on this walk (capped)
    recovery: dict | None = None     # pending Mission Recovery options awaiting the walker's choice
    chosen_recovery: dict | None = None
    last_report: float = 0.0
    status: str = "planning"        # planning | planned | walking | checkin | escalated | ended
    data: dict | None = None        # DemoData sent in walk.plan
    routes: dict | None = None      # engine route dicts {'best', 'fast'}
    started: float | None = None
    # live position, computed here from lngLat (the client's own progress value is never trusted)
    fix: list[float] | None = None
    fix_ts: float = 0.0
    meters: float = 0.0
    offset: float = 0.0
    anchor: list[float] | None = None
    moved_ts: float = 0.0
    asked_here: bool = False
    offroute: int = 0
    last_replan: float = 0.0
    gps_quiet_logged: bool = False
    # check-in and escalation ladder
    reply_deadline: float = 0.0
    escalate_deadline: float = 0.0
    escalated_reason: str = ""
    acked_by: str | None = None
    followed_up: bool = False
    sms_sent: bool = False
    checkins: int = 0
    ladder: int = 0                 # rescue ladder rung reached (0 = live link + SMS)
    last_where: str | None = None
    said: set = field(default_factory=set)
    _line: list | None = None
    _cum: list | None = None

    # ---------- the line the walker chose ----------
    @property
    def key(self) -> str:
        k = {"usual": "fast", "balanced": "balanced"}.get(self.choice, "best")
        return k if self.routes and k in self.routes else "best"

    def route(self) -> dict:
        return self.routes[self.key]

    def stats(self) -> dict:
        """Engine stats of the route being walked."""
        if self.key == "fast": return self.data["stats"]["shortest"]
        if self.key == "balanced": return next((o["stats"] for o in self.data.get("options") or [] if o["id"] == "balanced"), self.data["stats"]["hootroute"])
        return self.data["stats"]["hootroute"]

    def line(self) -> list:
        if self._line is None:
            self._line = self.route()["coords"]; self._cum = geo.cumulative(self._line)
        return self._line

    def cum(self) -> list: self.line(); return self._cum

    def total(self) -> float: return self.cum()[-1]

    def steps(self) -> list: return self.route()["steps"]

    def set_plan(self, data: dict, routes: dict):
        self.data, self.routes, self._line, self._cum = data, routes, None, None
        self.travel_mode = data.get("travelMode", self.travel_mode)
        self.travel_options = data.get("travelOptions", self.travel_options)

    @property
    def profile(self): return travel_profile(self.travel_mode, self.travel_options)

    def set_choice(self, choice: str):
        key = {"usual": "fast", "balanced": "balanced"}.get(choice, "best")
        if self.routes and not self.routes.get(key, self.routes["best"]).get("meets_limits", True): return
        self.choice = choice if choice in ("usual", "balanced") else "hootroute"; self._line = self._cum = None

    @property
    def active(self) -> bool: return self.status in ("walking", "checkin", "escalated")

    def first_name(self, who: str) -> str: return (who.split() or ["your guardian"])[0]

    def now(self) -> float: return time.time()
