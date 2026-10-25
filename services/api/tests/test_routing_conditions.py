"""Deterministic regression scenarios for time, distance, evidence and route selection."""
import asyncio
import json
import threading
from types import MethodType, SimpleNamespace

import networkx as nx
import numpy as np
import pytest

from hootroute_engine.engine import Engine
from hootroute_engine.scoring import Ctx, Norm, metrics, place_open, sample_route, uncovered_gap
from hootroute_engine.world import GTFS_COLS, World, day_minute
from hootroute_agents import evidence, hours_check
from hootroute_agents.preferences import choose_option


def place(ident="p", x=0, y=0, hours=None, **extra):
    return {"id": ident, "name": ident, "p": np.array([float(x), float(y)]), "ll": [x, y],
            "cat": "cafe", "hours": hours, "help": False, "pharm": False, "hours_source": None, **extra}


def world(points, links=None, places=()):
    graph = nx.Graph()
    for i, point in enumerate(points): graph.add_node(i, p=np.array(point, float), ll=list(point))
    for a, b, lit in links or [(i, i + 1, None) for i in range(len(points) - 1)]:
        length = float(np.linalg.norm(graph.nodes[a]["p"] - graph.nodes[b]["p"]))
        graph.add_edge(a, b, length=length, mid=(graph.nodes[a]["p"] + graph.nodes[b]["p"]) / 2, lit=lit, hw="residential", name="Test street")
    empty = np.zeros((0, 2))
    obj = SimpleNamespace(G=graph, nodes=list(graph), node_p=np.array(points, float), places=list(places),
                          place_p=np.array([p["p"] for p in places]).reshape(-1, 2), place_index={p["id"]: i for i, p in enumerate(places)},
                          lamps=empty, outages=empty, bus=empty, bart=[], proj=SimpleNamespace(xy=lambda lat, lon: np.array([lon, lat], float)))
    for method in ("nearest_node", "help_route_distances", "count_edges_near", "bart_running"):
        setattr(obj, method, MethodType(getattr(World, method), obj))
    World._edge_static(obj)
    return obj


@pytest.mark.parametrize("day,minute,spec,expected", [
    (4, 1445, "Fr 20:00-23:59; Sa 00:00-02:00", True),
    (4, 1445, "Fr 00:00-02:00; Sa off", False),
    (4, 1445, "Fr 20:00-02:00", True),
    (6, 1445, "Mo 00:00-02:00", True),
    (4, 1435, "Fr 20:00-23:59", True),
])
def test_arrival_weekday(day, minute, spec, expected):
    assert place_open(None, place(hours=spec), minute, Ctx(day, 1430)) is expected


def test_service_calendar_handles_gtfs_after_midnight():
    station = {"deps": {day: np.array([], float) for day in GTFS_COLS}}
    station["deps"]["friday"] = np.array([1450.0])
    assert World.bart_running(None, station, 4, 1445)
    assert World.bart_running(None, station, 5, 5)
    assert not World.bart_running(None, station, 6, 5)
    assert day_minute(6, 1445) == (0, 5)


@pytest.mark.parametrize("points", [[(0, 0), (25, 0)], [(0, 0), (6, 0), (12, 0), (18, 0)]])
def test_empty_gap_uses_actual_metres(points):
    data = metrics(world(points), Ctx(), list(range(len(points))))
    assert data["gap_m"] == pytest.approx(points[-1][0])
    assert data["gap_range"] == pytest.approx((0, points[-1][0]))


def test_longest_gap_and_length_weighting():
    assert uncovered_gap([False, False, True, False], np.array([3, 9, 16, 23]), np.array([6, 6, 8, 6])) == (12, (0, 12))
    w = world([(0, 0), (6, 0), (12, 0), (112, 0)], [(0, 1, "yes"), (1, 2, "yes"), (2, 3, "no")])
    assert metrics(w, Ctx(), [0, 1, 2, 3])["light"] == pytest.approx(12 / 112)
    assert len(sample_route(w, [0, 1])) == 4  # existing helper contract remains usable


def test_shop_is_evaluated_at_each_encounter():
    w = world([(0, 0), (200, 0)], places=[place(x=80, hours="Fr 00:00-00:01")])
    data = metrics(w, Ctx(4, 0), [0, 1])
    assert data["n_open"] == 1  # encountered before closing even though the closest point is later
    assert data["covered"].any()
    assert not data["covered"][-1]


@pytest.mark.parametrize("hours,entrance,access,credited", [
    (None, "main", None, False), ("24/7", None, None, False),
    ("24/7", "main", "private", False), ("24/7", "main", None, True),
])
def test_help_requires_hours_and_public_entry(hours, entrance, access, credited):
    facility = place(x=0, hours=hours, cat="hospital", help=True, entrance=entrance, access=access)
    data = metrics(world([(0, 0), (100, 0)], places=[facility]), Ctx(), [0, 1])
    assert (data["help_mean"] > 0) is credited


def test_help_across_disconnected_street_graph_gets_no_credit():
    facility = place(x=50, y=10, hours="24/7", cat="hospital", help=True, entrance="main")
    w = world([(0, 0), (100, 0), (50, 10), (60, 10)], [(0, 1, None), (2, 3, None)], [facility])
    result = metrics(w, Ctx(), [0, 1])
    assert result["help_mean"] == 0
    assert result["gap_m"] == 100


def tiny_engine():
    eng = Engine.__new__(Engine)
    eng.W = world([(0, 0), (100, 0), (200, 0), (100, 65)],
                  [(0, 1, "no"), (1, 2, "no"), (0, 3, "yes"), (3, 2, "yes")],
                  [place(x=100, y=65, hours="24/7")])
    eng.lock = threading.RLock(); eng.sessions = {}; eng.declared = {}; eng._quick = {}; eng._norms = {}
    eng.norm = lambda *a: Norm(dict.fromkeys(Norm.KEYS, 0), {"places_per_km": 5, "help_mean": 1, "gap_m": 200, "tpk": 10, "main": 1, "transit": 1})
    return eng


def test_route_limits_and_search_costs():
    eng = tiny_engine(); original = eng._astar; checked = []
    def astar(a, b, weight):
        assert all(d[weight] >= d["length"] for _, _, d in eng.W.G.edges(data=True))
        checked.append(weight)
        return original(a, b, weight)
    eng._astar = astar
    standard = eng.route("s", (0, 0), (0, 200), 4, 1410)
    assert len(checked) == 14
    assert standard["recommended"] == "best"
    assert all(0 <= r["score"] <= 100 for r in standard["routes"])
    limited = eng.route("s", (0, 0), (0, 200), 4, 1410, max_extra_minutes=0)
    assert limited["recommended"] == "fast"
    gap_limited = eng.route("s", (0, 0), (0, 200), 4, 1410, max_gap_m=150)
    assert next(r for r in gap_limited["routes"] if r["id"] == "best")["meets_limits"]
    assert not gap_limited["routes"][0]["meets_limits"]
    with pytest.raises(ValueError, match="No candidate"):
        eng.route("s", (0, 0), (0, 200), 4, 1410, max_gap_m=1)
    with pytest.raises(ValueError, match="finite"):
        eng.route("s", (0, 0), (0, 200), 4, 1410, max_extra_minutes=float("nan"))


def test_preferences_do_not_override_route_limits():
    options = [{"id": "fast", "meetsLimits": False, "stats": {"minutes": 1, "score": 90}},
               {"id": "best", "label": "HootRoute", "meetsLimits": True, "stats": {"minutes": 2, "score": 80}}]
    assert choose_option(options, {"fastest": True})["optionId"] == "best"


def test_check_priority_targets_gap_and_stale_hours():
    eng = SimpleNamespace(W=world([(0, 0), (100, 0)], places=[place("early", 5), place("gap", 95),
        place("stale", 85, hours="24/7", hours_source="apify-batch", hours_at="2000-01-01T00:00:00Z")]))
    selected = hours_check.unknowns(eng, [[0, 0], [100, 0]], 4, 1410, 2, gap_range=(80, 100))
    assert {p["id"] for p in selected} == {"gap", "stale"}
    assert next(p for p in selected if p["id"] == "stale")["checkReason"] == "stale_hours"


def test_refresh_and_reuse_restore_evidence_without_new_charge(monkeypatch, tmp_path):
    eng = tiny_engine(); eng.W.places[0].update(hours=None, hours_source=None)
    path = tmp_path / "hours.json"; monkeypatch.setattr(hours_check, "LIVE_FILE", path)
    checked = evidence.now_iso()
    path.write_text(json.dumps({"p": {"kind": "published_hours", "opening_hours": "24/7", "name": "p", "checked_at": checked,
                                      "confidence": 1, "source": "apify-live"}}), encoding="utf-8")
    def forbidden(*args): raise AssertionError("A recent completed check must not be billed again")
    monkeypatch.setattr(hours_check, "check", forbidden)
    result = asyncio.run(hours_check.investigate(eng, [{"id": "p", "name": "p"}]))
    assert result["reused"] == 1 and result["changed"] == 1
    assert eng.W.places[0]["hours"] == "24/7" and eng.W.places[0]["hours_at"] == checked
    changed = hours_check.apply(eng, [{"id": "p", "status": "hours found", "hours": "Mo-Fr 09:00-17:00", "checkedAt": checked, "confidence": 1}], persist=False)
    assert changed == 1 and eng.W.places[0]["hours"] != "24/7"
    eng.W.places[0].update(hours="24/7", hours_source="osm")
    assert hours_check.apply(eng, [{"id": "p", "status": "closed", "hours": "off", "checkedAt": checked}], persist=False) == 0


def test_plan_cache_separates_limits_and_empty_env_disables_file_key(monkeypatch):
    from hootroute_api.app import plan_key, PlanReq
    from hootroute_api import settings
    a = {"lat": 37.78, "lon": -122.4}
    assert plan_key(a, a, 4, 1410) != plan_key(a, a, 4, 1410, {"maxGapM": 300})
    with pytest.raises(ValueError): PlanReq(origin=a, destination=a, maxExtraMinutes=-1)
    monkeypatch.setitem(settings._FILE, "UNIT_TEST_PROVIDER", "file-value")
    monkeypatch.setenv("UNIT_TEST_PROVIDER", "")
    assert settings.env("UNIT_TEST_PROVIDER") == ""


def test_restart_retains_a_newer_unknown_listing(monkeypatch, tmp_path):
    eng = tiny_engine()
    eng.W.places[0].update(hours="24/7", hours_source="apify-batch", hours_at="2000-01-01T00:00:00Z")
    monkeypatch.setattr(hours_check, "LIVE_FILE", tmp_path / "hours.json")
    result = {"id": "p", "name": "p", "status": "no hours", "hours": None, "checkedAt": evidence.now_iso(), "source": "https://example.org/listing"}
    assert hours_check.record([result])
    assert hours_check.load_live(eng) == 1
    assert eng.W.places[0]["hours"] is None
    assert not list(tmp_path.glob("*.tmp"))


def test_legacy_calibration_is_not_reused(monkeypatch, tmp_path):
    import hootroute_engine.scoring as scoring
    monkeypatch.setattr(scoring, "CACHE", tmp_path)
    (tmp_path / "norms").mkdir()
    old = tmp_path / "norms" / "norm_0_0_4_0.json"
    old.write_text(json.dumps({"lo": dict.fromkeys(Norm.KEYS, 999), "hi": dict.fromkeys(Norm.KEYS, 1000)}), encoding="utf-8")
    monkeypatch.setattr(Norm, "reference_paths", lambda *a: [[0, 1]])
    reference = Norm.build(world([(0, 0), (25, 0)]), Ctx(4, 0), (0, 0))
    assert reference.hi["gap_m"] == 25
    assert (tmp_path / "norms" / "norm_v2_0_0_4_0.json").exists()


def test_live_choice_cannot_bypass_limits():
    from hootroute_agents.walk import Walk
    walk = Walk(id="w", walker="Walker", guardian="Contact", guardian_phone=None, guardian_url="", origin={}, dest={}, day=4, minute=0,
                routes={"best": {"meets_limits": True}, "fast": {"meets_limits": False}})
    walk.set_choice("usual")
    assert walk.choice == "hootroute"
