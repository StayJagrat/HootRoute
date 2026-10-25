"""Night Walk Score. Deterministic, route-level, time-aware. No model is involved in producing the number.

A route is sampled every 10 m and each sample gets an arrival minute (departure + distance / walking speed).
Every component is evaluated at that minute, so a shop only counts if its listed hours cover the moment you pass it.

Points (of 100): open places 20 | gaps between open places 15 | open help points 15 | street lighting 20 | main roads 10 | transit running 10 | fewer turns 10.
Crime is not an input. All components except lighting are scored against typical walks in the same area and hour (10th to 90th percentile).
"""
import json, math, random
from dataclasses import dataclass, field

import networkx as nx
import numpy as np

from .config import CACHE, STEP, WALK_SPEED, WEIGHTS
from .world import World, day_minute, is_open, public_entrance

MAIN = {"primary", "secondary", "tertiary", "primary_link", "secondary_link", "tertiary_link"}


def clip(x, lo=0.0, hi=1.0): return float(min(hi, max(lo, x)))


@dataclass
class Ctx:
    """When the walk happens, and what places have told us since the data was cached."""
    day: int = 4                                   # 0 = Monday
    minute: int = 22 * 60 + 50
    overrides: dict = field(default_factory=dict)  # place id -> minute (of the same night, may exceed 1440) until which it declares itself open

    def key(self): return (self.day, self.minute, tuple(sorted(self.overrides.items())))


def place_open(W: World, pl, minute, ctx: Ctx):
    until = ctx.overrides.get(pl["id"])
    if until is not None and minute < until: return True
    day, local = day_minute(ctx.day, minute)
    return bool(is_open(pl["hours"], day, local))


def sample_route(W: World, path, *, with_widths=False):
    pts = [W.G.nodes[n]["p"] for n in path]; samples, dists, edges, widths = [], [], [], []; cum = 0.0
    for i in range(len(pts) - 1):
        a, b = pts[i], pts[i + 1]; L = float(np.hypot(*(b - a))); d = W.G.edges[path[i], path[i + 1]]; k = max(1, math.ceil(L / STEP))
        for j in range(k):
            f = (j + 0.5) / k; samples.append(a + (b - a) * f); dists.append(cum + L * f); edges.append(d); widths.append(L / k)
        cum += L
    if not samples: raise ValueError("A route must contain at least one street segment.")
    result = (np.array(samples), np.array(dists), edges, cum)
    return (*result, np.array(widths)) if with_widths else result


def uncovered_gap(covered, distances, widths):
    """Longest contiguous uncovered sample interval, measured in metres along the route."""
    best = run = 0.0; start = 0.0; interval = None
    for i, present in enumerate(covered):
        if present:
            run = 0.0
            continue
        if run == 0: start = float(distances[i] - widths[i] / 2)
        run += float(widths[i])
        if run > best:
            best = run; interval = (start, float(distances[i] + widths[i] / 2))
    return best, interval


def turns_per_km(W: World, path, total):
    n = 0
    for i in range(1, len(path) - 1):
        if W.G.degree(path[i]) < 3: continue
        a, b, c = (W.G.nodes[path[j]]["p"] for j in (i - 1, i, i + 1)); v1, v2 = b - a, c - b
        if abs(math.degrees(math.atan2(v1[0] * v2[1] - v1[1] * v2[0], v1 @ v2))) > 35: n += 1
    return n / max(total / 1000, 0.1)


def metrics(W: World, ctx: Ctx, path):
    P, D, edges, total, widths = sample_route(W, path, with_widths=True); t = ctx.minute + D / WALK_SPEED / 60.0
    mean = lambda values: float(np.average(values, weights=widths))
    lo, hi = P.min(0) - 220, P.max(0) + 220
    box = lambda A: A[(A[:, 0] >= lo[0]) & (A[:, 0] <= hi[0]) & (A[:, 1] >= lo[1]) & (A[:, 1] <= hi[1])] if len(A) else A
    dmat = lambda A: (np.hypot(P[:, None, 0] - A[None, :, 0], P[:, None, 1] - A[None, :, 1]) if len(A) else np.full((len(P), 1), 1e9))
    near_open = np.zeros(len(P), bool); open_idx = {}; help_distances = []; unknown = 0; help_unverified = 0
    cand = np.where((W.place_p[:, 0] >= lo[0]) & (W.place_p[:, 0] <= hi[0]) & (W.place_p[:, 1] >= lo[1]) & (W.place_p[:, 1] <= hi[1]))[0]
    if len(cand):
        dm = dmat(W.place_p[cand]); jmin = dm.argmin(axis=0); dmin = dm.min(axis=0)
        for c, idx in enumerate(cand):
            if dmin[c] > 150: continue
            pl = W.places[idx]; j = int(jmin[c])
            # A place may close between two encounters with the route. Evaluate
            # each passing minute instead of spreading one open state along it.
            times = {int(tm): place_open(W, pl, tm, ctx) for tm in np.unique(t.astype(int))}
            opened = np.array([times[int(tm)] for tm in t])
            if pl["hours"] is None and pl["id"] not in ctx.overrides and dmin[c] <= 50: unknown += 1
            accessible = pl.get("access") not in {"no", "private"} and pl.get("foot") not in {"no", "private"}
            nearby_open = opened & (dm[:, c] <= 50) & accessible
            if not pl["help"] and nearby_open.any():
                closest = int(np.where(nearby_open, dm[:, c], np.inf).argmin())
                open_idx[idx] = (int(D[closest]), int(dm[closest, c])); near_open |= nearby_open
            if pl["help"] or pl["pharm"] or pl["hours"] == "24/7":
                if public_entrance(pl) and hasattr(W, "help_route_distances"):
                    reachable = W.help_route_distances(pl, path, D)
                    help_distances.append(np.where(opened, reachable, np.inf))
                else: help_unverified += 1
    # A station schedule contributes to transit, but does not establish public
    # entrance access or staffing and therefore does not fill a help-coverage gap.
    dh = np.min(help_distances, axis=0) if help_distances else np.full(len(P), np.inf)
    help_prox = np.clip(1 - dh / 200, 0, 1); covered = near_open | (dh <= 100)
    gap_m, gap_range = uncovered_gap(covered, D, widths)
    la, ou = box(W.lamps), box(W.outages); dl = dmat(la).min(axis=1); lamp_near = dl <= 30
    lit_tag = np.array([e.get("lit") for e in edges], dtype=object); lit = (lamp_near | (lit_tag == "yes")) & (lit_tag != "no")
    known = lamp_near | (lit_tag == "yes") | (lit_tag == "no") | (dl <= 60); out_near = dmat(ou).min(axis=1) <= 40 if len(ou) else np.zeros(len(P), bool); lit &= ~out_near
    main = mean([e["hw"] in MAIN for e in edges]); tr = np.zeros(len(P)); bu = box(W.bus)
    if len(bu): tr = np.maximum(tr, 0.4 * (dmat(bu).min(axis=1) <= 150))
    for b in W.bart:
        if not (lo[0] <= b["p"][0] <= hi[0] and lo[1] <= b["p"][1] <= hi[1]): continue
        near = np.hypot(P[:, 0] - b["p"][0], P[:, 1] - b["p"][1]) <= 250
        if near.any():
            running = np.array([W.bart_running(b, ctx.day, tm) if n else False for n, tm in zip(near, t)])
            tr = np.maximum(tr, near * running)
    return dict(places_per_km=len(open_idx) / max(total / 1000, 0.1), n_open=len(open_idx), gap_m=gap_m, help_mean=mean(help_prox), light=mean(lit), main=main,
                transit=mean(tr), tpk=turns_per_km(W, path, total), length=float(total), minutes=float(total / WALK_SPEED / 60), unknown_hours=unknown, light_known=mean(known),
                help_unverified=help_unverified,
                outages_near=int((np.diff(np.r_[0, out_near.astype(int)]) == 1).sum()), gap_range=gap_range,
                covered=covered, P=P, D=D, open_idx=open_idx, lit=lit, out_near=out_near)


class Norm:
    """Reference distribution: the same metrics on ordinary walks in the same neighbourhood, at the same day and half hour.

    The city is cut into 2 km cells; each cell gets its own reference set, so a walk is compared with typical walks around it
    (downtown against downtown, the Sunset against the Sunset), never with the whole city."""
    KEYS = ("places_per_km", "help_mean", "gap_m", "tpk", "main", "transit")
    FLOOR = dict(places_per_km=2.0, help_mean=0.10, gap_m=150.0, tpk=3.0, main=0.25, transit=0.25)   # smallest meaningful spread; stops a dead area from saturating at 100
    CELL = 2000.0
    N_REF = 20
    VERSION = 2  # previous cache values used sample counts and assumed help availability

    def __init__(self, lo, hi): self.lo, self.hi = lo, hi
    def n(self, k, x): return clip((x - self.lo[k]) / max(self.hi[k] - self.lo[k], self.FLOOR.get(k, 1e-9)))

    @classmethod
    def cell_of(cls, xy): return (int(xy[0] // cls.CELL), int(xy[1] // cls.CELL))

    @classmethod
    def reference_paths(cls, W: World, cell, n=None, seed=3):
        n = n or cls.N_REF; rng = random.Random(seed * 100003 + cell[0] * 1009 + cell[1])
        cx, cy = (cell[0] + 0.5) * cls.CELL, (cell[1] + 0.5) * cls.CELL
        near = np.where(np.hypot(W.node_p[:, 0] - cx, W.node_p[:, 1] - cy) <= cls.CELL * 0.9)[0]
        if len(near) < 50: near = np.argsort(np.hypot(W.node_p[:, 0] - cx, W.node_p[:, 1] - cy))[:400]
        out, tries = [], 0
        h = lambda u, v: float(np.hypot(*(W.G.nodes[u]["p"] - W.G.nodes[v]["p"])))
        while len(out) < n and tries < n * 40:
            tries += 1; a, b = rng.sample(list(near), 2); d = float(np.hypot(*(W.node_p[a] - W.node_p[b])))
            if 700 < d < 1800:
                try: out.append(nx.astar_path(W.G, W.nodes[a], W.nodes[b], heuristic=h, weight="length"))
                except nx.NetworkXNoPath: pass
        return out

    @classmethod
    def build(cls, W: World, ctx: Ctx, cell):
        day, minute = day_minute(ctx.day, ctx.minute)
        f = CACHE / "norms" / f"norm_v{cls.VERSION}_{cell[0]}_{cell[1]}_{day}_{minute // 30}.json"
        if f.exists(): d = json.loads(f.read_text(encoding="utf-8")); return cls(d["lo"], d["hi"])
        refs = cls.reference_paths(W, cell)
        ms = [metrics(W, Ctx(day, (minute // 30) * 30), p) for p in refs]; lo, hi = {}, {}
        for k in cls.KEYS: v = np.array([m[k] for m in ms]) if ms else np.zeros(1); lo[k], hi[k] = float(np.percentile(v, 10)), float(np.percentile(v, 90))
        f.parent.mkdir(exist_ok=True); f.write_text(json.dumps(dict(lo=lo, hi=hi, n=len(ms))), encoding="utf-8"); return cls(lo, hi)


def score(m, N: Norm):
    comp = dict(places=N.n("places_per_km", m["places_per_km"]), gaps=1 - N.n("gap_m", m["gap_m"]), help=N.n("help_mean", m["help_mean"]), light=m["light"],
                main=N.n("main", m["main"]), transit=N.n("transit", m["transit"]), turns=1 - N.n("tpk", m["tpk"]))
    pts = {k: round(WEIGHTS[k] * v, 1) for k, v in comp.items()}
    return round(sum(pts.values()), 1), pts, comp
