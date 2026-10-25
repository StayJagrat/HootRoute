"""Mode restrictions are evaluated against map tags; unknown access is never invented."""
import json
import threading
from types import SimpleNamespace

import numpy as np
import pytest

from hootroute_engine.mobility import allows, cycle_lane, directions, incline_pct, travel_profile
from hootroute_engine.scoring import Ctx, metrics
from hootroute_engine.world import World
from hootroute_api.app import PlanReq, plan_key
from hootroute_api.db import DB
from hootroute_agents.runtime import Runtime
from hootroute_agents.agents import promote
from hootroute_agents.plan_data import build_plan
from test_routing_conditions import world


@pytest.mark.parametrize("tags,expected", [
    ({"highway": "steps"}, False), ({"highway": "footway"}, False),
    ({"highway": "footway", "bicycle": "yes"}, True),
    ({"highway": "residential", "foot": "no", "bicycle": "yes"}, True),
    ({"highway": "residential", "bicycle": "no"}, False),
    ({"highway": "path", "bicycle": "dismount"}, False),
    ({"highway": "cycleway"}, True),
])
def test_cycle_access(tags, expected):
    assert allows(tags, travel_profile("cycle")) is expected


@pytest.mark.parametrize("tags,result", [
    ({"oneway": "yes"}, (1,)), ({"oneway": "-1"}, (-1,)),
    ({"oneway": "yes", "oneway:bicycle": "no"}, (1, -1)),
    ({"oneway": "yes", "cycleway": "opposite_lane"}, (1, -1)),
    ({"junction": "roundabout"}, (1,)),
    ({"bicycle:backward": "no"}, (1,)),
])
def test_cycle_directions(tags, result):
    assert directions(tags, travel_profile("cycle")) == result
    assert directions(tags, travel_profile()) == (1, -1)


@pytest.mark.parametrize("tags", [
    {"highway": "steps"}, {"wheelchair": "no"}, {"wheelchair": "limited"},
    {"incline": "6%"}, {"incline": "-8%"}, {"width": "60 cm"},
    {"kerb": "raised"}, {"kerb:height": "10 cm"}, {"surface": "gravel"}, {"smoothness": "bad"},
])
def test_wheelchair_excludes_recorded_barriers(tags):
    assert not allows({"highway": "footway", **tags}, travel_profile("wheelchair"))


def test_unknown_access_and_user_options():
    assert allows({"highway": "footway"}, travel_profile("wheelchair"))
    assert not allows({"highway": "footway"}, travel_profile("wheelchair", {"requireKnownAccess": True}))
    assert allows({"highway": "footway", "wheelchair": "yes"}, travel_profile("wheelchair", {"requireKnownAccess": True}))
    assert allows({"highway": "footway", "surface": "gravel"}, travel_profile("wheelchair", {"avoidRoughSurfaces": False}))
    assert allows({"highway": "footway", "incline": "6%"}, travel_profile("wheelchair", {"maxInclinePct": 8}))
    assert incline_pct("up") is None and incline_pct("down") is None
    assert incline_pct("-3%") == 3
    assert incline_pct("5°") == pytest.approx(8.748866, abs=.00001)
    assert cycle_lane({"cycleway:right": "track"}) and not cycle_lane({"cycleway": "shared_lane"})


def test_pace_changes_arrival_and_access_coverage():
    w = world([(0, 0), (200, 0)])
    walk = metrics(w, Ctx(), [0, 1])
    cycle = metrics(w, Ctx(profile=travel_profile("cycle")), [0, 1])
    wheelchair = metrics(w, Ctx(profile=travel_profile("wheelchair")), [0, 1])
    assert cycle["minutes"] < walk["minutes"] < wheelchair["minutes"]
    assert wheelchair["access_known_pct"] == 0 and wheelchair["incline_unknown_pct"] == 100
    assert wheelchair["gap_m"] == cycle["gap_m"] == 200


def test_profile_networks_do_not_mutate_walking(monkeypatch, tmp_path):
    import hootroute_engine.world as module
    ways = [
        {"type": "way", "id": 1, "nodes": [0, 1], "geometry": [{"lat": 0, "lon": 0}, {"lat": 0, "lon": 20}], "tags": {"highway": "steps"}},
        {"type": "way", "id": 2, "nodes": [0, 2, 1], "geometry": [{"lat": 0, "lon": 0}, {"lat": 10, "lon": 10}, {"lat": 0, "lon": 20}],
         "tags": {"highway": "residential", "oneway": "yes", "wheelchair": "yes", "surface": "asphalt"}},
        {"type": "way", "id": 3, "nodes": [1, 3], "geometry": [{"lat": 0, "lon": 20}, {"lat": 0, "lon": 40}],
         "tags": {"highway": "cycleway", "foot": "no", "bicycle": "yes"}},
    ]
    (tmp_path / "osm_ways.json").write_text(json.dumps(ways), encoding="utf-8")
    monkeypatch.setattr(module, "CACHE", tmp_path)
    w = World.__new__(World); w.proj = SimpleNamespace(xy=lambda lat, lon: np.array([lon, lat], float))
    w._load_graph()
    empty = np.zeros((0, 2)); w.lamps = w.outages = w.bus = empty
    w._edge_static()
    w._avoid_segments = ("walking edges",)
    original = set(w.G.edges())
    cycle = w.for_profile(travel_profile("cycle"))
    chair = w.for_profile(travel_profile("wheelchair"))
    assert w.G.has_edge(0, 1) and not cycle.G.has_edge(0, 1) and not chair.G.has_edge(0, 1)
    assert cycle.G.has_edge(0, 2) and not cycle.G.has_edge(2, 0)
    assert cycle.G.has_edge(1, 3) and not w.G.has_node(3)
    assert set(w.G.edges()) == original
    assert not hasattr(cycle, "_avoid_segments") and not hasattr(chair, "_avoid_segments")
    assert w.for_profile(travel_profile("cycle")) is cycle


def test_cache_and_validation_separate_modes_and_options():
    a = {"lat": 37.78, "lon": -122.4}
    keys = [plan_key(a, a, 4, 1410, travel_mode=mode) for mode in ("walk", "cycle", "wheelchair")]
    assert len(set(keys)) == 3
    assert plan_key(a, a, 4, 1410, travel_mode="cycle", travel_options={"speedKmh": 10}) != keys[1]
    for mode, speed in (("cycle", 1), ("wheelchair", 12)):
        with pytest.raises(ValueError): PlanReq(origin=a, destination=a, travelMode=mode, travelOptions={"speedKmh": speed})
    with pytest.raises(ValueError): PlanReq(origin=a, destination=a, travelMode="car")
    with pytest.raises(ValueError): travel_profile("cycle", {"speedKmh": 0})


def test_mode_and_options_survive_database_restart(tmp_path):
    path = tmp_path / "walks.db"
    db = DB(path)
    record = {"id": "w", "created_at": 1, "status": "planned", "walker_token": "test", "walker_name": "Rider", "guardian_name": "Contact",
              "guardian_phone": None, "origin": {}, "destination": {}, "depart_day": 4, "depart_minute": 1410, "choice": "hootroute",
              "thresholds": {}, "replay": False, "time_scale": 1, "travel_mode": "cycle", "travel_options": {"speedKmh": 20}, "notify_consent": False, "sharing": True}
    db.create_walk(record); db.conn.close()
    reopened = DB(path); saved = reopened.walk("w")
    assert saved["travel_mode"] == "cycle" and saved["travel_options"]["speedKmh"] == 20
    walk = Runtime.make_walk(saved, "")
    assert walk.travel_mode == "cycle" and walk.profile.speed == pytest.approx(20 / 3.6)
    reopened.conn.close()


def test_recovery_switch_uses_selected_route_access_details():
    original = {"wheelchairTagsPct": 80}
    replacement = {"wheelchairTagsPct": 25}
    data = {"route": [[0, 0], [1, 1]], "stats": {"hootroute": {}}, "routeSteps": {"hootroute": []}, "modeConditions": original}
    candidate = {"coords": [[0, 0], [2, 2]], "score": 40, "gap": {"m": 100}, "minutes": 5, "steps": [], "modeConditions": replacement}
    updated, routes = promote(data, {"best": {}, "fast": candidate}, "fast")
    assert updated["modeConditions"] == replacement and routes["best"] == candidate
    assert data["modeConditions"] == original


@pytest.mark.parametrize("mode,options,distance", [("cycle", {}, 300), ("wheelchair", {"requireKnownAccess": True}, 75)])
def test_missing_mode_connection_explains_options(mode, options, distance):
    mapped = SimpleNamespace(nearest_node=lambda *args: (1, distance))
    engine = SimpleNamespace(lock=threading.RLock(), world=lambda profile: mapped)
    with pytest.raises(ValueError, match="selected travel options"):
        build_plan(engine, 37.78, -122.4, "Destination", origin=(37.79, -122.41), travel_mode=mode, travel_options=options)
