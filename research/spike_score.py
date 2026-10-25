"""Lantern data spike: real SF data -> segment graph -> Lantern Score -> two routes.

Run:  .venv/bin/python data/spike_score.py [--day Fr] [--hour 23]
Writes data/out/segments.geojson, data/out/routes.json and prints a summary.
Sources: OSM via Overpass, SF 311 (vw6y-z8j6), SFPD incidents (wg3w-h783).
"""
import argparse, hashlib, json, math, re, sys, time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import networkx as nx
import numpy as np
import requests

ROOT = Path(__file__).parent
CACHE = ROOT / "cache"; CACHE.mkdir(exist_ok=True)
OUT = ROOT / "out"; OUT.mkdir(exist_ok=True)
UA = {"User-Agent": "lantern-calhacks/0.1", "Accept": "*/*"}

# south, west, north, east. About 1.1 km x 1.7 km.
BBOX = (37.7840, -122.4160, 37.7940, -122.4000)
WALKABLE = "footway|pedestrian|residential|tertiary|secondary|primary|living_street|service|unclassified|path|steps|tertiary_link|secondary_link"
WEIGHTS = dict(light=0.35, alive=0.30, help=0.20, incident=0.10, camera=0.05)
DAYS = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]


def cached(key, fn):
    f = CACHE / (hashlib.md5(key.encode()).hexdigest() + ".json")
    if f.exists():
        return json.loads(f.read_text())
    data = fn()
    f.write_text(json.dumps(data))
    return data


def overpass(q):
    def go():
        for attempt in range(3):
            r = requests.post("https://overpass-api.de/api/interpreter", data={"data": q}, headers=UA, timeout=90)
            if r.status_code == 200:
                return r.json()
            time.sleep(4 * (attempt + 1))
        r.raise_for_status()
    return cached(q, go)


def socrata(dataset, params):
    def go():
        r = requests.get(f"https://data.sf.gov/resource/{dataset}.json", params=params, headers=UA, timeout=60)
        r.raise_for_status()
        return r.json()
    return cached(dataset + json.dumps(params, sort_keys=True), go)


# ---------- geometry helpers (equirectangular, fine at city scale) ----------
LAT0 = math.radians((BBOX[0] + BBOX[2]) / 2)
MX = 111_320 * math.cos(LAT0)
MY = 110_540


def xy(lat, lon):
    return np.array([(lon - BBOX[1]) * MX, (lat - BBOX[0]) * MY])


def dist_pts(p, pts):
    return np.hypot(pts[:, 0] - p[0], pts[:, 1] - p[1]) if len(pts) else np.array([])


# ---------- opening_hours: minimal parser for the common OSM patterns ----------
def is_open(spec, day_idx, minutes):
    """True / False / None (unknown). Handles '24/7', 'Mo-Fr 09:00-17:00; Sa 10:00-14:00', 'off'."""
    if not spec:
        return None
    spec = spec.strip()
    if spec == "24/7":
        return True
    result = None
    for rule in [r.strip() for r in spec.split(";") if r.strip()]:
        m = re.match(r"^((?:Mo|Tu|We|Th|Fr|Sa|Su|PH)[-,\w]*)?\s*(.*)$", rule)
        days_s, rest = (m.group(1) or "Mo-Su"), m.group(2).strip()
        days = set()
        for part in days_s.split(","):
            if "-" in part and part[:2] in DAYS and part[3:5] in DAYS:
                a, b = DAYS.index(part[:2]), DAYS.index(part[3:5])
                days |= {(a + i) % 7 for i in range(((b - a) % 7) + 1)}
            elif part[:2] in DAYS:
                days.add(DAYS.index(part[:2]))
        if rest in ("off", "closed"):
            if day_idx in days:
                result = False
            continue
        spans = re.findall(r"(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})", rest)
        if not spans:
            continue
        for h1, m1, h2, m2 in spans:
            s, e = int(h1) * 60 + int(m1), int(h2) * 60 + int(m2)
            if e <= s:  # crosses midnight
                if (day_idx in days and minutes >= s) or ((day_idx - 1) % 7 in days and minutes < e):
                    return True
            elif day_idx in days and s <= minutes < e:
                return True
        if day_idx in days:
            result = False if result is None else result
    return result


# ---------- load data ----------
def load_ways():
    s, w, n, e = BBOX
    q = f'[out:json][timeout:80];way["highway"~"^({WALKABLE})$"]["access"!~"private|no"]({s},{w},{n},{e});out geom;'
    return [el for el in overpass(q)["elements"] if el["type"] == "way"]


def load_points():
    s, w, n, e = BBOX
    q = f"""[out:json][timeout:80];
(
 node["highway"="street_lamp"]({s},{w},{n},{e});
 node["man_made"="surveillance"]({s},{w},{n},{e});
 nwr["shop"]({s},{w},{n},{e});
 nwr["amenity"~"^(restaurant|cafe|bar|pub|fast_food|pharmacy|bank|cinema|theatre|nightclub|police|fire_station|hospital|clinic|fuel|convenience)$"]({s},{w},{n},{e});
);
out center tags;"""
    return overpass(q)["elements"]


def load_311(since):
    s, w, n, e = BBOX
    rows = socrata("vw6y-z8j6", {
        "$where": f"service_name='Streetlights' AND requested_datetime > '{since}' AND within_box(point_geom,{s},{w},{n},{e})",
        "$limit": 5000})
    return [r for r in rows if r.get("lat")]


def load_311_history(since):
    """All streetlight cases since `since`: every report marks a spot where a lamp stood (presence evidence, not density)."""
    s, w, n, e = BBOX
    rows = socrata("vw6y-z8j6", {
        "$select": "lat,long",
        "$where": f"service_name='Streetlights' AND requested_datetime > '{since}' AND within_box(point_geom,{s},{w},{n},{e})",
        "$limit": 50000})
    return [r for r in rows if r.get("lat")]


def load_incidents(since):
    s, w, n, e = BBOX
    rows = socrata("wg3w-h783", {
        "$where": f"incident_datetime > '{since}' AND within_box(point,{s},{w},{n},{e})",
        "$limit": 20000})
    return [r for r in rows if r.get("latitude")]


# ---------- build graph ----------
def build_graph(ways):
    G = nx.Graph()
    for wy in ways:
        nodes, geom, tags = wy["nodes"], wy["geometry"], wy.get("tags", {})
        for i in range(len(nodes) - 1):
            a, b = nodes[i], nodes[i + 1]
            pa, pb = xy(geom[i]["lat"], geom[i]["lon"]), xy(geom[i + 1]["lat"], geom[i + 1]["lon"])
            length = float(np.hypot(*(pa - pb)))
            if length < 1:
                continue
            G.add_node(a, p=pa, ll=(geom[i]["lat"], geom[i]["lon"]))
            G.add_node(b, p=pb, ll=(geom[i + 1]["lat"], geom[i + 1]["lon"]))
            G.add_edge(a, b, length=length, mid=(pa + pb) / 2, name=tags.get("name", ""), lit=tags.get("lit"),
                       hw=tags.get("highway"), way=wy["id"])
    # keep the largest connected component
    comp = max(nx.connected_components(G), key=len)
    return G.subgraph(comp).copy()


def score_graph(G, lamps, cams, places, helps, r311, incidents, day_idx, minutes, include_incidents=True):
    P = {k: np.array(v) if v else np.zeros((0, 2)) for k, v in dict(lamps=lamps, cams=cams, places=places, helps=helps, r311=r311).items()}
    inc_p = np.array([i[0] for i in incidents]) if incidents else np.zeros((0, 2))
    inc_w = np.array([i[1] for i in incidents]) if incidents else np.zeros(0)
    for a, b, d in G.edges(data=True):
        m, L = d["mid"], d["length"]
        reach = 25 + L / 2
        n_lamps = int((dist_pts(m, P["lamps"]) <= reach).sum())
        lit = d["lit"]
        light = min(1.0, n_lamps / (L / 40 + 1))
        known = n_lamps > 0 or lit in ("yes", "no")
        if lit == "yes":
            light = max(light, 0.75)
        elif lit == "no":
            light = min(light, 0.15)
        elif not known:
            light = 0.35  # unknown prior, flagged low confidence
        out_311 = int((dist_pts(m, P["r311"]) <= 40 + L / 2).sum())
        light = max(0.0, light - 0.25 * out_311)
        open_n = int((dist_pts(m, P["places"]) <= 50 + L / 2).sum())
        alive = min(1.0, open_n / 3)
        dh = dist_pts(m, P["helps"])
        help_ = float(max(0.0, 1 - dh.min() / 200)) if len(dh) else 0.0
        cam = min(1.0, int((dist_pts(m, P["cams"]) <= 50 + L / 2).sum()) / 2)
        risk = 0.0
        if include_incidents and len(inc_p):
            near = dist_pts(m, inc_p) <= 80 + L / 2
            risk = min(1.0, float(inc_w[near].sum()) / 4)
        w = WEIGHTS
        s = 100 * (w["light"] * light + w["alive"] * alive + w["help"] * help_ + w["incident"] * (1 - risk) + w["camera"] * cam)
        if not include_incidents:  # score used for validation: incidents left out, weights renormalised
            s = 100 * (w["light"] * light + w["alive"] * alive + w["help"] * help_ + w["camera"] * cam) / (1 - w["incident"])
        d.update(score=round(min(100.0, s), 1), light=round(light, 2), alive=round(alive, 2), help=round(help_, 2),
                 risk=round(risk, 2), cam=round(cam, 2), n_lamps=n_lamps, n_open=open_n, n311=out_311, lit_known=known)


def route_stats(G, path, empty_below=40):
    segs = [G.edges[path[i], path[i + 1]] for i in range(len(path) - 1)]
    total = sum(s["length"] for s in segs)
    mean = sum(s["score"] * s["length"] for s in segs) / total
    run = best = 0.0
    for s in segs:
        run = run + s["length"] if s["score"] < empty_below else 0.0
        best = max(best, run)
    return dict(length_m=round(total), minutes=round(total / 1.4 / 60, 1), mean_score=round(mean, 1), longest_empty_m=round(best),
                strip=[round(s["score"]) for s in segs])


def rank(x):
    order = np.argsort(x, kind="stable"); r = np.empty(len(x)); r[order] = np.arange(len(x)); return r


def spearman(x, y):
    rx, ry = rank(np.asarray(x)), rank(np.asarray(y))
    return float(np.corrcoef(rx, ry)[0, 1])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--day", default="Fr"); ap.add_argument("--hour", type=int, default=23)
    ap.add_argument("--lam", type=float, default=3.0)
    ap.add_argument("--empty-pct", type=float, default=25.0, help="a segment is 'empty' if it scores below this percentile of the area")
    ap.add_argument("--bbox", default=None, help="south,west,north,east")
    ap.add_argument("--tag", default="out", help="output subfolder name")
    args = ap.parse_args()
    global BBOX, LAT0, MX, OUT
    if args.bbox:
        BBOX = tuple(float(v) for v in args.bbox.split(","))
        LAT0 = math.radians((BBOX[0] + BBOX[2]) / 2)
        MX = 111_320 * math.cos(LAT0)
    OUT = ROOT / args.tag; OUT.mkdir(exist_ok=True)
    day_idx, minutes = DAYS.index(args.day), args.hour * 60

    t0 = time.time()
    ways = load_ways(); pts = load_points()
    since311 = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%dT00:00:00")
    sinceInc = (datetime.now(timezone.utc) - timedelta(days=90)).strftime("%Y-%m-%dT00:00:00")
    r311 = load_311(since311); inc = load_incidents(sinceInc)
    hist = load_311_history("2020-01-01T00:00:00")
    print(f"loaded: {len(ways)} ways, {len(pts)} osm points, {len(r311)} 311 streetlight reports (30d), {len(inc)} incidents (90d) in {time.time()-t0:.1f}s")

    G = build_graph(ways)
    print(f"graph: {G.number_of_nodes()} nodes, {G.number_of_edges()} segments, {sum(d['length'] for *_, d in G.edges(data=True))/1000:.1f} km of street")

    lamps, cams, places, helps = [], [], [], []
    open_unknown = open_known = 0
    for el in pts:
        lat = el.get("lat") or el.get("center", {}).get("lat"); lon = el.get("lon") or el.get("center", {}).get("lon")
        if lat is None:
            continue
        t = el.get("tags", {}); p = xy(lat, lon)
        if t.get("highway") == "street_lamp":
            lamps.append(p)
        elif t.get("man_made") == "surveillance":
            cams.append(p)
        else:
            am = t.get("amenity", "")
            op = is_open(t.get("opening_hours"), day_idx, minutes)
            if op is None:
                open_unknown += 1
            else:
                open_known += 1
            if am in ("police", "fire_station", "hospital") or (am == "pharmacy" and op is True) or t.get("opening_hours") == "24/7":
                if am in ("police", "fire_station", "hospital") or op is True:
                    helps.append(p)
            if op is True:
                places.append(p)
    print(f"osm: {len(lamps)} lamps, {len(cams)} cameras, {len(places)} places open at {args.day} {args.hour}:00 "
          f"({open_known} with parseable hours, {open_unknown} without hours), {len(helps)} help points")

    seen = set()
    for r in hist:  # dedupe to ~12 m cells so one pole reported 30 times counts once
        p = xy(float(r["lat"]), float(r["long"])); key = (int(p[0] // 12), int(p[1] // 12))
        if key not in seen:
            seen.add(key); lamps.append(p)
    print(f"lamp evidence: {len(seen)} distinct pole locations from {len(hist)} 311 cases since 2020, plus OSM lamps -> {len(lamps)} lamp points")
    r311p = [xy(float(r["lat"]), float(r["long"])) for r in r311 if r.get("status_description") == "Open" or True]
    night = lambda r: (int(r["incident_time"][:2]) >= 20 or int(r["incident_time"][:2]) < 5) if r.get("incident_time") else False
    heavy = ("Robbery", "Assault", "Weapons Offense", "Homicide", "Rape", "Sex Offense")
    inc_pts = [(xy(float(r["latitude"]), float(r["longitude"])), 1.0 if r.get("incident_category") in heavy else 0.4)
               for r in inc if night(r)]
    print(f"night incidents (8pm-5am) used: {len(inc_pts)}")

    score_graph(G, lamps, cams, places, helps, r311p, inc_pts, day_idx, minutes, include_incidents=True)
    scores = np.array([d["score"] for *_, d in G.edges(data=True)])
    print(f"segment score: mean {scores.mean():.1f}, p10 {np.percentile(scores,10):.0f}, p90 {np.percentile(scores,90):.0f}; "
          f"{(scores<40).mean()*100:.0f}% of segments under a fixed 40")
    empty_below = float(np.percentile(scores, args.empty_pct))
    print(f"'empty stretch' threshold = area p{args.empty_pct:.0f} = {empty_below:.1f}")
    unk = np.mean([not d["lit_known"] for *_, d in G.edges(data=True)])
    print(f"light data unknown on {unk*100:.0f}% of segments (prior used, flagged low confidence)")

    # routes between two far apart nodes
    nodes = list(G.nodes)
    P = np.array([G.nodes[n]["p"] for n in nodes])
    def nearest(lat, lon):
        return nodes[int(np.argmin(dist_pts(xy(lat, lon), P)))]
    S, W, N, E = BBOX
    f = lambda a, b, t: a + (b - a) * t
    pairs = [((f(S, N, .15), f(W, E, .08)), (f(S, N, .85), f(W, E, .92))),
             ((f(S, N, .9), f(W, E, .1)), (f(S, N, .12), f(W, E, .88))),
             ((f(S, N, .5), f(W, E, .05)), (f(S, N, .55), f(W, E, .95)))]
    routes = []
    for (a_ll, b_ll) in pairs:
        a, b = nearest(*a_ll), nearest(*b_ll)
        shortest = nx.shortest_path(G, a, b, weight="length")
        cost = lambda u, v, d: d["length"] * (1 + args.lam * (1 - d["score"] / 100) + (1.0 if d["score"] < empty_below else 0.0))
        safe = nx.shortest_path(G, a, b, weight=cost)
        rs, rl = route_stats(G, shortest, empty_below), route_stats(G, safe, empty_below)
        coords = lambda path: [[G.nodes[n]["ll"][1], G.nodes[n]["ll"][0]] for n in path]
        routes.append(dict(from_=a_ll, to=b_ll, shortest=dict(rs, coords=coords(shortest)), lantern=dict(rl, coords=coords(safe))))
        print(f"\nroute {a_ll} -> {b_ll}")
        print(f"  shortest : {rs['length_m']} m, {rs['minutes']} min, mean score {rs['mean_score']}, longest empty stretch {rs['longest_empty_m']} m")
        print(f"  lantern  : {rl['length_m']} m, {rl['minutes']} min, mean score {rl['mean_score']}, longest empty stretch {rl['longest_empty_m']} m  (+{rl['minutes']-rs['minutes']:.1f} min)")

    # validation: score without incidents vs held-out night incidents, per segment
    score_graph(G, lamps, cams, places, helps, r311p, inc_pts, day_idx, minutes, include_incidents=False)
    base = [d["score"] for *_, d in G.edges(data=True)]
    held = []
    ip = np.array([p for p, _ in inc_pts]) if inc_pts else np.zeros((0, 2))
    iw = np.array([w for _, w in inc_pts]) if inc_pts else np.zeros(0)
    for *_, d in G.edges(data=True):
        near = dist_pts(d["mid"], ip) <= 80 + d["length"] / 2
        held.append(float(iw[near].sum()) / (d["length"] / 100 + 1))
    rho = spearman(base, held)
    q = np.percentile(base, [25, 75]); base_a = np.array(base); held_a = np.array(held)
    low, high = held_a[base_a <= q[0]].mean(), held_a[base_a >= q[1]].mean()
    print(f"\nvalidation (score WITHOUT incidents vs night incident load per segment): spearman rho = {rho:+.2f}; "
          f"mean incident load bottom-quartile {low:.2f} vs top-quartile {high:.2f}")

    # ---- city layer: synthetic walkers -> "walker-minutes in the dark" per street ----
    import random
    random.seed(7)
    score_graph(G, lamps, cams, places, helps, r311p, inc_pts, day_idx, minutes, include_incidents=True)
    N_WALKERS = 1500
    exposure = {}  # (u, v) -> minutes walked on that segment by synthetic walkers while it is 'empty'
    for _ in range(N_WALKERS):
        a, b = random.sample(nodes, 2)
        if np.hypot(*(G.nodes[a]["p"] - G.nodes[b]["p"])) < 400:
            continue
        path = nx.shortest_path(G, a, b, weight="length")
        for u, v in zip(path, path[1:]):
            d = G.edges[u, v]
            if d["score"] < empty_below:
                exposure[(u, v)] = exposure.get((u, v), 0.0) + d["length"] / 1.4 / 60
    by_street = {}
    for (u, v), mins in exposure.items():
        d = G.edges[u, v]; name = d["name"] or "(unnamed way)"
        e = by_street.setdefault(name, dict(minutes=0.0, segs=0, unknown_light=0, low_light=0, no_open=0, n311=0))
        e["minutes"] += mins; e["segs"] += 1
        e["unknown_light"] += 0 if d["lit_known"] else 1
        e["low_light"] += 1 if (d["lit_known"] and d["light"] < 0.4) else 0
        e["no_open"] += 1 if d["n_open"] == 0 else 0
        e["n311"] += d["n311"]
    ranked = sorted(by_street.items(), key=lambda kv: -kv[1]["minutes"])[:10]
    total = sum(exposure.values())
    print(f"\ndarkness debt: {N_WALKERS} synthetic walkers (uniform demand, shortest path), {total:.0f} walker-minutes on 'empty' segments")
    for name, e in ranked:
        cause = "light data missing" if e["unknown_light"] >= max(e["low_light"], 1) else "confirmed low light"
        print(f"  {name[:28]:28s} {e['minutes']:6.1f} walker-min  {e['segs']:3d} segs  {cause}; open places on {e['segs']-e['no_open']}/{e['segs']} segs")
    (OUT / "darkness_debt.json").write_text(json.dumps([dict(street=k, **v) for k, v in ranked]))

    feats = [dict(type="Feature", properties={k: v for k, v in d.items() if k in ("score", "light", "alive", "help", "risk", "n_lamps", "n_open", "n311", "name")},
                  geometry=dict(type="LineString", coordinates=[[G.nodes[a]["ll"][1], G.nodes[a]["ll"][0]], [G.nodes[b]["ll"][1], G.nodes[b]["ll"][0]]]))
             for a, b, d in G.edges(data=True)]
    score_graph(G, lamps, cams, places, helps, r311p, inc_pts, day_idx, minutes, include_incidents=True)
    (OUT / "segments.geojson").write_text(json.dumps(dict(type="FeatureCollection", features=feats)))
    (OUT / "routes.json").write_text(json.dumps(routes))
    print(f"\nwrote {OUT}/segments.geojson ({len(feats)} segments) and routes.json")


if __name__ == "__main__":
    main()
