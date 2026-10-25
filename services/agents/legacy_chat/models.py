"""Typed messages shared by every Streetwise agent. Both sides of a send_and_receive must import these same definitions."""
from uagents import Model


# ---- shop agents -----------------------------------------------------------------------------------------------
class HoursQuery(Model):
    place_id: str
    day: int            # 0=Mon .. 6=Sun, same as the engine
    minute: int         # minutes after midnight of `day` at which the walker passes the shop (can exceed 1440)


class HoursReply(Model):
    place_id: str
    name: str
    open_at_minute: bool
    open_until: int | None      # minute offset after midnight of the query day, None if not open
    simulated: bool
    note: str = ""


class HoursDeclaration(Model):
    """Pushed by a shop agent: 'I am open until open_until'. Scout validates the sender before trusting it."""
    place_id: str
    name: str
    open_until: int
    simulated: bool = True


# ---- walk safety loop: scout <-> watcher <-> rescuer ---------------------------------------------------------------
class WalkStart(Model):
    session: str
    user: str                     # chat address of the user (replies go through scout)
    label: str
    expected_minutes: float
    check_every_s: int
    reply_deadline_s: int
    route_coords: list[list[float]]    # [lon, lat] pairs, as the engine returns them
    destination: str


class WalkStop(Model):
    session: str
    user: str


class UserNotice(Model):
    """Watcher/rescuer -> scout: relay this text to the user in their chat."""
    user: str
    text: str


class CheckInAck(Model):
    session: str
    user: str


class RescueTrigger(Model):
    session: str
    user: str
    label: str
    reason: str
    minutes_overdue: float
    route_coords: list[list[float]]
    destination: str


class RescueDone(Model):
    session: str
    user: str
    packet_path: str
    summary: str


# ---- reporter ----------------------------------------------------------------------------------------------------
class ReportRequest(Model):
    session: str
    user: str
    issue: str
    place_label: str
    lat: float | None = None
    lon: float | None = None
    notes: str = ""


class ReportDraft(Model):
    session: str
    path: str
    text: str
    submitted: bool = False       # always False: this system never submits a report


# ---- night auditor -----------------------------------------------------------------------------------------------
class AuditRequest(Model):
    session: str = "auditor"


class AuditReport(Model):
    ok: bool
    summary: str
    path: str = ""
