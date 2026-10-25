"""Streetwise Night Walk Score: a deterministic, route-level, time-aware score. No LLM in the loop.

A route is sampled every 10 m. Each sample gets an arrival time (departure + distance / walking speed),
and every component is evaluated at that time, so a shop only counts if it is open when you pass it.

Components (points out of 100):
  open places along the route 20 | gaps between open places 15 | open help points 15 | street lighting 20
  main-road share 10 | transit running at your time 10 | fewer turns 10
Crime is not an input. The score describes conditions on the street, not safety.

Run:  .venv/bin/python data/walkscore.py [--hour 22 --minute 50 --day Fr]
Writes data/out_walk/demo.json for the prototype UI.
"""
import argparse, collections, csv, io, json, math, random, sys, zipfile
from pathlib import Path

import numpy as np
import networkx as nx
import requests

sys.path.insert(0, str(Path(__file__).parent))
import spike_score as S

ROOT = Path(__file__).parent
OUT = ROOT / "out_walk"; OUT.mkdir(exist_ok=True)
SPEED = 1.35            # m/s
STEP = 10.0             # sample spacing, m
WEIGHTS = dict(places=20, gaps=15, help=15, light=20, main=10, transit=10, turns=10)
MAIN = {"primary", "secondary", "tertiary", "primary_link", "secondary_link", "tertiary_link"}
HELP_AMENITY = {"police", "fire_station", "hospital"}
LATE_OK = {"cafe", "restaurant", "bar", "pub", "fast_food", "convenience", "pharmacy", "nightclub"}


def clip(x, lo=0.0, hi=1.0):
    return float(min(hi, max(lo, x)))


# ---------------- data ----------------
def load_transit_osm():
    s, w, n, e = S.BBOX
    q = f'[out:json][timeout:60];(node["highway"="bus_stop"]({s},{w},{n},{e});node["railway"="tram_stop"]({s},{w},{n},{e}););out;'
    return [S.xy(el["lat"], el["lon"]) for el in S.overpass(q)["elements"]]


def load_bart(day_col, minutes, window=20):
    """BART stations inside the box with the number of departures within +/- window minutes of `minutes`."""
    f = ROOT / "cache" / "bart_gtfs.zip"
    if not f.exists():
        r = requests.get("https://www.bart.gov/dev/schedules/google_transit.zip", headers=S.UA, timeout=60); r.raise_for_status()
        f.write_bytes(r.content)
    z = zipfile.ZipFile(f)
    rd = lambda n: list(csv.DictReader(io.TextIOWrapper(z.open(n), encoding="utf-8-sig")))
    stops = {r["stop_id"]: r for r in rd("stops.txt")}
    active = {r["service_id"] for r in rd("calendar.txt") if r[day_col] == "1"}
    trips = {r["trip_id"] for r in rd("trips.txt") if r["service_id"] in active}
    S0, W0, N0, E0 = S.BBOX
    inbox = {sid for sid, r in stops.items() if r.get("stop_lat") and S0 <= float(r["stop_lat"]) <= N0 and W0 <= float(r["stop_lon"]) <= E0}
    deps = collections.defaultdict(list)
    for r in csv.DictReader(io.TextIOWrapper(z.open("stop_times.txt"), encoding="utf-8-sig")):
        if r["stop_id"] in inbox and r["trip_id"] in trips:
            h, m, _ = r["departure_time"].split(":"); deps[r["stop_id"]].append(int(h) * 60 + int(m))
    out = []
    for sid in inbox:
        n_near = sum(1 for t in deps[sid] if abs(t - minutes) <= window)
        out.append(dict(name=stops[sid].get("stop_name", "BART"), p=S.xy(float(stops[sid]["stop_lat"]), float(stops[sid]["stop_lon"])),
                        departures=n_near, last=max(deps[sid]) if deps[sid] else None))
    return out


class World:
    def __init__(self, day, minutes):
        self.day, self.minutes = S.DAYS.index(day), minutes
        self.G = S.build_graph(S.load_ways())
        pts = S.load_points(); self.places = []; lamps = []; cams = []; helps_always = []
        for el in pts:
            lat = el.get("lat") or el.get("center", {}).get("lat"); lon = el.get("lon") or el.get("center", {}).get("lon")
            if lat is None: continue
            t = el.get("tags", {}); p = S.xy(lat, lon)
            if t.get("highway") == "street_lamp": lamps.append(p)
            elif t.get("man_made") == "surveillance": cams.append(p)
            else:
                am = t.get("amenity", "")
                self.places.append(dict(p=p, name=t.get("name"), cat=am or t.get("shop", "shop"), hours=t.get("opening_hours"),
                                        help=am in HELP_AMENITY, always=am in HELP_AMENITY, pharm=am == "pharmacy", override=None))
        hist = S.load_311_history("2020-01-01T00:00:00"); seen = set(); self.lamp_evidence = 0
        for r in hist:
            p = S.xy(float(r["lat"]), float(r["long"])); k = (int(p[0] // 12), int(p[1] // 12))
            if k not in seen: seen.add(k); lamps.append(p); self.lamp_evidence += 1
        self.lamps = np.array(lamps); self.cams = np.array(cams)
        since = (S.datetime.now(S.timezone.utc) - S.timedelta(days=30)).strftime("%Y-%m-%dT00:00:00")
        self.outages = np.array([S.xy(float(r["lat"]), float(r["long"])) for r in S.load_311(since)] or np.zeros((0, 2)))
        self.bus = np.array(load_transit_osm() or np.zeros((0, 2)))
        self.bart = load_bart(["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"][self.day], minutes)

    def place_open(self, pl, minute):
        if pl["override"] is not None: return pl["override"] > minute
        if pl["always"]: return True
        o = S.is_open(pl["hours"], self.day, int(minute) % 1440)
        return bool(o)


# ---------------- route scoring ----------------
def sample_route(G, path):
    pts = [G.nodes[n]["p"] for n in path]; seg = []; cum = 0.0; samples = []; edge_of = []
    for i in range(len(pts) - 1):
        a, b = pts[i], pts[i + 1]; L = float(np.hypot(*(b - a)))
        d = G.edges[path[i], path[i + 1]]
        k = max(1, int(L // STEP))
        for j in range(k):
            f = (j + 0.5) / k; samples.append((a + (b - a) * f, cum + L * f)); edge_of.append(d)
        cum += L
    return np.array([s[0] for s in samples]), np.array([s[1] for s in samples]), edge_of, cum


def turns_per_km(G, path, total):
    n = 0
    for i in range(1, len(path) - 1):
        if G.degree(path[i]) < 3: continue
        a, b, c = G.nodes[path[i - 1]]["p"], G.nodes[path[i]]["p"], G.nodes[path[i + 1]]["p"]
        v1, v2 = b - a, c - b
        ang = abs(math.degrees(math.atan2(v1[0] * v2[1] - v1[1] * v2[0], v1 @ v2)))
        if ang > 35: n += 1
    return n / max(total / 1000, 0.1)


def metrics(W, path, depart):
    G = W.G; P, D, edges, total = sample_route(G, path)
    t = depart + D / SPEED / 60.0                                   # arrival minute at every sample
    dist = lambda arr: (np.hypot(P[:, None, 0] - arr[None, :, 0], P[:, None, 1] - arr[None, :, 1]) if len(arr) else np.full((len(P), 1), 1e9))
    # places and help points open at the time we pass them
    open_pl, help_pts, near_open = set(), [], np.zeros(len(P), bool)
    unknown_near = 0
    for idx, pl in enumerate(W.places):
        d = np.hypot(P[:, 0] - pl["p"][0], P[:, 1] - pl["p"][1]); j = int(np.argmin(d))
        if d[j] > 150: continue
        is_open = W.place_open(pl, t[j])
        if pl["hours"] is None and not pl["always"] and pl["override"] is None and d[j] <= 50: unknown_near += 1
        if is_open and not pl["help"]:
            if d[j] <= 50: open_pl.add(idx)
            near_open |= d <= 50
        if is_open and (pl["help"] or pl["pharm"] or pl["hours"] == "24/7"): help_pts.append((pl["p"], pl["cat"]))
    for b in W.bart:
        j = int(np.argmin(np.hypot(P[:, 0] - b["p"][0], P[:, 1] - b["p"][1])))
        if b["departures"] > 0 and np.hypot(*(P[j] - b["p"])) <= 250: help_pts.append((b["p"], "BART"))
    hp = np.array([h[0] for h in help_pts]) if help_pts else np.zeros((0, 2))
    help_prox = np.clip(1 - dist(hp).min(axis=1) / 200, 0, 1) if len(hp) else np.zeros(len(P))
    near_help = (dist(hp).min(axis=1) <= 100) if len(hp) else np.zeros(len(P), bool)
    covered = near_open | near_help
    # longest uncovered run
    best = run = 0
    for c in covered:
        run = 0 if c else run + 1; best = max(best, run)
    gap_m = best * STEP
    # gap location for the UI
    gap_start = gap_end = 0; run = 0
    for i, c in enumerate(covered):
        run = 0 if c else run + 1
        if run * STEP >= gap_m and gap_m > 0: gap_end = i; gap_start = i - run + 1
    # lighting: lamp or lit tag, minus open outage reports
    lamp_near = dist(W.lamps).min(axis=1) <= 30
    lit_tag = np.array([e.get("lit") for e in edges], dtype=object)
    lit = lamp_near | (lit_tag == "yes"); lit &= lit_tag != "no"
    known = lamp_near | (lit_tag == "yes") | (lit_tag == "no") | (dist(W.lamps).min(axis=1) <= 60)
    out_near = dist(W.outages).min(axis=1) <= 40 if len(W.outages) else np.zeros(len(P), bool)
    lit &= ~out_near
    # main roads, transit
    main = np.mean([e["hw"] in MAIN for e in edges])
    tr = np.zeros(len(P))
    if len(W.bus): tr = np.maximum(tr, 0.4 * (dist(W.bus).min(axis=1) <= 150))
    for b in W.bart:
        near = np.hypot(P[:, 0] - b["p"][0], P[:, 1] - b["p"][1]) <= 250
        tr = np.maximum(tr, near * (1.0 if b["departures"] > 0 else 0.0))
    return dict(places_per_km=len(open_pl) / max(total / 1000, 0.1), n_open=len(open_pl), gap_m=gap_m, help_mean=float(help_prox.mean()),
                light=float(lit.mean()), main=float(main), transit=float(tr.mean()), tpk=turns_per_km(G, path, total),
                length=float(total), minutes=float(total / SPEED / 60), unknown_hours=unknown_near, light_known=float(known.mean()),
                outages_near=int(out_near.sum() > 0 and (np.diff(np.r_[0, out_near.astype(int)]) == 1).sum()),
                gap_range=(float(D[gap_start]), float(D[min(gap_end, len(D) - 1)] + STEP)) if gap_m else None,
                covered=covered, P=P, D=D, open_idx=open_pl, out_near=out_near, lit=lit)


class Norm:
    def __init__(self, W, depart, n=80, seed=3):
        random.seed(seed); nodes = list(W.G.nodes); ms = []
        while len(ms) < n:
            a, b = random.sample(nodes, 2); d = np.hypot(*(W.G.nodes[a]["p"] - W.G.nodes[b]["p"]))
            if not 900 < d < 2000: continue
            ms.append(metrics(W, nx.shortest_path(W.G, a, b, weight="length"), depart))
        self.lo, self.hi = {}, {}
        for k in ("places_per_km", "help_mean", "gap_m", "tpk", "main", "transit"):
            v = np.array([m[k] for m in ms]); self.lo[k], self.hi[k] = float(np.percentile(v, 10)), float(np.percentile(v, 90))

    def n(self, k, x): return clip((x - self.lo[k]) / max(self.hi[k] - self.lo[k], 1e-9))


def score(m, N):
    # every component except lighting is scored against typical walks in this area at this hour (p10 -> 0, p90 -> 1)
    comp = dict(places=N.n("places_per_km", m["places_per_km"]), gaps=1 - N.n("gap_m", m["gap_m"]), help=N.n("help_mean", m["help_mean"]),
                light=m["light"], main=N.n("main", m["main"]), transit=N.n("transit", m["transit"]), turns=1 - N.n("tpk", m["tpk"]))
    pts = {k: round(WEIGHTS[k] * v, 1) for k, v in comp.items()}
    return round(sum(pts.values()), 1), pts, comp


def candidates(W, a, b, depart, quick):
    G = W.G; short = nx.shortest_path(G, a, b, weight="length"); L0 = sum(G.edges[u, v]["length"] for u, v in zip(short, short[1:]))
    paths = {tuple(short)}
    for lam in (1, 2, 4, 8):
        cost = lambda u, v, d, lam=lam: d["length"] * (1 + lam * (1 - quick.get(frozenset((u, v)), 30) / 100))
        paths.add(tuple(nx.shortest_path(G, a, b, weight=cost)))
    try:
        for i, p in enumerate(nx.shortest_simple_paths(G, a, b, weight="length")):
            if i >= 4: break
            if sum(G.edges[u, v]["length"] for u, v in zip(p, p[1:])) <= 1.35 * L0: paths.add(tuple(p))
    except nx.NetworkXNoPath:
        pass
    return short, [list(p) for p in paths]


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--day", default="Fr"); ap.add_argument("--hour", type=int, default=22); ap.add_argument("--minute", type=int, default=50)
    ap.add_argument("--pairs", type=int, default=120); ap.add_argument("--max-extra", type=float, default=0.25)
    args = ap.parse_args(); depart = args.hour * 60 + args.minute
    W = World(args.day, depart); G = W.G
    print(f"graph {G.number_of_edges()} segments | places {len(W.places)} | lamp points {len(W.lamps)} (311 evidence {W.lamp_evidence}) | open outages {len(W.outages)} | bus stops {len(W.bus)} | BART stations {len(W.bart)}")
    for b in W.bart: print(f"   BART {b['name']}: {b['departures']} departures within 20 min of {args.hour}:{args.minute:02d}; last {b['last']//60}:{b['last']%60:02d}" if b["last"] else f"   BART {b['name']}: none")
    N = Norm(W, depart)
    # quick per-edge score for candidate generation (conditions at departure time, crime excluded)
    open_pts = [pl["p"] for pl in W.places if W.place_open(pl, depart) and not pl["help"]]
    helps = [pl["p"] for pl in W.places if pl["help"] or (pl["pharm"] and W.place_open(pl, depart))]
    S.score_graph(G, list(W.lamps), list(W.cams), open_pts, helps, list(W.outages), [], W.day, depart, include_incidents=False)
    quick = {frozenset((a, b)): d["score"] for a, b, d in G.edges(data=True)}
    random.seed(21); nodes = list(G.nodes); rows = []
    while len(rows) < args.pairs:
        a, b = random.sample(nodes, 2); d = np.hypot(*(G.nodes[a]["p"] - G.nodes[b]["p"]))
        if not 1000 < d < 1900: continue
        short, cands = candidates(W, a, b, depart, quick)
        ev = []
        for p in cands:
            m = metrics(W, p, depart); sc, pts, comp = score(m, N); ev.append((sc, p, m, pts))
        fast = next(e for e in ev if e[1] == short); lim = fast[2]["minutes"] * (1 + args.max_extra)
        best = max((e for e in ev if e[2]["minutes"] <= lim), key=lambda e: e[0])
        rows.append(dict(a=a, b=b, fast=fast, best=best))
    gains = np.array([r["best"][0] - r["fast"][0] for r in rows]); extra = np.array([r["best"][2]["minutes"] - r["fast"][2]["minutes"] for r in rows])
    gap_f = np.array([r["fast"][2]["gap_m"] for r in rows]); gap_b = np.array([r["best"][2]["gap_m"] for r in rows])
    same = np.mean([r["best"][1] == r["fast"][1] for r in rows])
    print(f"\n{len(rows)} random walks of 1.0-1.9 km, depart {args.day} {args.hour}:{args.minute:02d}, extra walking capped at +{args.max_extra:.0%}")
    print(f"  fastest route is already the best-scoring: {same*100:.0f}% of walks")
    print(f"  score gain: median {np.median(gains):+.1f}, p75 {np.percentile(gains,75):+.1f}, p90 {np.percentile(gains,90):+.1f}; mean extra time {extra.mean():.1f} min (median {np.median(extra):.1f})")
    print(f"  longest empty stretch: median {np.median(gap_f):.0f} m -> {np.median(gap_b):.0f} m")
    print(f"  mean fastest score {np.mean([r['fast'][0] for r in rows]):.1f}, mean best score {np.mean([r['best'][0] for r in rows]):.1f}")
    # demo walk: gain near the 75th percentile, small extra time, length >= 1.3 km (not the best case)
    p75 = np.percentile(gains, 75)
    pool = [r for r in rows if r["best"][1] != r["fast"][1] and r["best"][2]["minutes"] - r["fast"][2]["minutes"] <= 3.5 and r["fast"][2]["length"] >= 1300]
    demo = min(pool, key=lambda r: abs((r["best"][0] - r["fast"][0]) - p75))
    f, b = demo["fast"], demo["best"]
    print(f"\nDEMO WALK (gain near p75): fastest {f[0]} ({f[2]['minutes']:.1f} min, gap {f[2]['gap_m']:.0f} m, {f[2]['n_open']} open places)  ->  best {b[0]} ({b[2]['minutes']:.1f} min, gap {b[2]['gap_m']:.0f} m, {b[2]['n_open']} open places)")
    for nm, e in (("fastest", f), ("best", b)): print(f"   {nm}: {e[3]}")

    # what-if: one currently closed place inside the fastest route's empty stretch declares it is staying open until 1 AM
    T = f  # (score, path, metrics, points) of the fastest route; the best route is already at the ceiling for open places
    cand_places = []; gr = T[2]["gap_range"]
    for idx, pl in enumerate(W.places):
        if pl["help"] or pl["override"] is not None or pl["cat"] not in LATE_OK: continue  # only places that could plausibly stay open late
        dd = np.hypot(T[2]["P"][:, 0] - pl["p"][0], T[2]["P"][:, 1] - pl["p"][1]); j = int(np.argmin(dd))
        if dd[j] <= 50 and not W.place_open(pl, depart + 10) and (gr is None or gr[0] - 30 <= T[2]["D"][j] <= gr[1] + 30): cand_places.append(idx)
    best_delta = (0, None)
    for idx in cand_places[:80]:
        W.places[idx]["override"] = 25 * 60
        sc = score(metrics(W, T[1], depart), N)[0]; W.places[idx]["override"] = None
        if sc - T[0] > best_delta[0]: best_delta = (sc - T[0], idx)
    whatif = None
    print(f"what-if candidates inside the gap: {len(cand_places)}")
    if best_delta[1] is not None:
        pl = W.places[best_delta[1]]; pl["override"] = 25 * 60
        m2 = metrics(W, T[1], depart); sc2, pts2, _ = score(m2, N); pl["override"] = None
        d_ = np.hypot(T[2]["P"][:, 0] - pl["p"][0], T[2]["P"][:, 1] - pl["p"][1]); j_ = int(np.argmin(d_))
        whatif = dict(name=pl["name"] or pl["cat"].replace("_", " ").title(), cat=pl["cat"], at=round(float(T[2]["D"][j_])), score_before=T[0], score_after=sc2, pts_after=pts2,
                      gap_before=round(T[2]["gap_m"]), gap_after=round(m2["gap_m"]), hours_listed=pl["hours"])
        print(f"WHAT-IF place agent: '{whatif['name']}' ({pl['cat']}, listed hours {pl['hours']}) stays open until 1 AM -> fastest route {T[0]} -> {sc2}, longest gap {T[2]['gap_m']:.0f} -> {m2['gap_m']:.0f} m")

    S0, W0 = S.BBOX[0], S.BBOX[1]
    ll = lambda p: [round(W0 + p[0] / S.MX, 5), round(S0 + p[1] / S.MY, 5)]
    def pack(e, label):
        sc, path, m, pts = e
        shops = []
        for idx in sorted(m["open_idx"]):
            pl = W.places[idx]; d = np.hypot(m["P"][:, 0] - pl["p"][0], m["P"][:, 1] - pl["p"][1]); j = int(np.argmin(d))
            shops.append(dict(d=round(float(m["D"][j])), off=round(float(d[j])), name=pl["name"], cat=pl["cat"], p=ll(pl["p"])))
        return dict(label=label, score=sc, points=pts, minutes=round(m["minutes"], 1), km=round(m["length"] / 1000, 2), n_open=m["n_open"], gap_m=round(m["gap_m"]),
                    gap_range=[round(x) for x in m["gap_range"]] if m["gap_range"] else None, light_pct=round(100 * m["light"]), main_pct=round(100 * m["main"]),
                    turns_per_km=round(m["tpk"], 1), outages_near=m["outages_near"], light_known_pct=round(100 * m["light_known"]), unknown_hours_nearby=m["unknown_hours"],
                    coords=[ll(G.nodes[n]["p"]) for n in path], shops=shops, covered=[bool(x) for x in m["covered"][::3]])
    streets = [[*ll(G.nodes[a]["p"]), *ll(G.nodes[b]["p"]), round(d["score"])] for a, b, d in G.edges(data=True)]
    out = dict(bbox=S.BBOX, depart=f"{args.day} {args.hour}:{args.minute:02d}", weights=WEIGHTS, norm=dict(lo=N.lo, hi=N.hi), streets=streets,
               fastest=pack(f, "Fastest route"), best=pack(b, "Streetwise route"), whatif=whatif,
               bart=[dict(name=x["name"], p=ll(x["p"]), departures=x["departures"]) for x in W.bart],
               stats=dict(n_walks=len(rows), same_pct=round(100 * same), gain_median=round(float(np.median(gains)), 1), gain_p75=round(float(p75), 1), extra_mean=round(float(extra.mean()), 1),
                          extra_median=round(float(np.median(extra)), 1), gap_fast_median=round(float(np.median(gap_f))), gap_best_median=round(float(np.median(gap_b))),
                          places_total=len(W.places), places_no_hours=sum(1 for p in W.places if p["hours"] is None and not p["always"]), lamp_points=len(W.lamps), lamp_evidence=W.lamp_evidence,
                          open_outages=len(W.outages)))
    (OUT / "demo.json").write_text(json.dumps(out, separators=(",", ":")))
    print(f"\nwrote {OUT/'demo.json'} ({(OUT/'demo.json').stat().st_size/1024:.0f} KB)")


if __name__ == "__main__":
    main()
