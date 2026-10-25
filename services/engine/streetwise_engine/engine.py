"""Engine: the one object the API and the agents talk to. Everything it returns is plain JSON-able data.

Agents live above this layer. They decide when to call it and what to do with the answer; they never compute the score.
"""
import math, threading, time
from typing import Callable, Optional

import networkx as nx
import numpy as np

from .config import BBOX, STEP, WALK_SPEED, WEIGHTS
from .scoring import Ctx, Norm, metrics, place_open, score
from .world import DAYS, LATE_OK, World

Emit = Optional[Callable[[str, str, str, dict], None]]    # (agent, kind, message, data)
LANDMARKS = [  # approximate coordinates, used for search and snapping only
    ("Union Square", 37.7880, -122.4075), ("Powell St BART", 37.7844, -122.4079), ("Montgomery St BART", 37.7894, -122.4013), ("Embarcadero BART", 37.7929, -122.3969),
    ("Civic Center BART", 37.7796, -122.4139), ("City Hall", 37.7793, -122.4193), ("Ferry Building", 37.7955, -122.3937), ("Moscone Center", 37.7842, -122.4016),
    ("Salesforce Transit Center", 37.7896, -122.3969), ("Transamerica Pyramid", 37.7952, -122.4028), ("Chinatown Gate", 37.7908, -122.4058), ("Yerba Buena Gardens", 37.7847, -122.4023),
    ("Asian Art Museum", 37.7802, -122.4160), ("Westfield San Francisco Centre", 37.7842, -122.4072), ("Hallidie Plaza", 37.7846, -122.4073),
]


_SUFFIX = {"Street": "St", "Avenue": "Ave", "Boulevard": "Blvd", "Place": "Pl", "Terrace": "Ter", "Drive": "Dr", "Lane": "Ln", "Alley": "Aly"}


def short_street(name: str) -> str:
    """'Howard Street' -> 'Howard St' (only the last word, so 'Avenue of the Palms' stays as it is)."""
    head, _, last = name.rpartition(" ")
    return f"{head} {_SUFFIX[last]}" if head and last in _SUFFIX else name


class Engine:
    def __init__(self, bbox=BBOX):
        t0 = time.time(); self.W = World(bbox); self.lock = threading.RLock(); self.sessions: dict[str, Ctx] = {}
        self.declared: dict[int, dict[str, int]] = {}   # city-wide shopkeeper declarations: night weekday -> place id -> open-until minute
        self._norms = {}; self._quick = {}
        self.boot_seconds = round(time.time() - t0, 1)

    # ---------- context ----------
    def ctx(self, session: str, day: int, minute: int) -> Ctx:
        base = self.sessions.setdefault(session, Ctx(day, minute)); return Ctx(day, minute, {**self.declared.get(day, {}), **base.overrides})

    def set_declarations(self, declared: dict[int, dict[str, int]]):
        """Replace the city-wide shopkeeper declarations (loaded from the database). Every later ctx() sees them."""
        with self.lock: self.declared = {int(d): dict(v) for d, v in declared.items()}

    def norm(self, ctx: Ctx, near=None) -> Norm:
        """Reference distribution for the neighbourhood of `near` (projected x, y in metres, or a (lon, lat) list via center_of)."""
        cell = Norm.cell_of(near if near is not None else self.W.proj.xy(37.7890, -122.4080))
        k = (cell, ctx.day, ctx.minute // 30)
        if k not in self._norms: self._norms[k] = Norm.build(self.W, ctx, cell)
        return self._norms[k]

    def center_of(self, coords):
        """Projected midpoint of a route given as [[lon, lat], ...]."""
        lon, lat = coords[len(coords) // 2]; return self.W.proj.xy(lat, lon)

    # ---------- quick per-edge quality (used to steer the search, never shown as the score) ----------
    def quick(self, ctx: Ctx):
        k = (ctx.day, ctx.minute // 15, tuple(sorted(ctx.overrides.items())))
        if k in self._quick: return self._quick[k]
        W = self.W; m = (ctx.minute // 15) * 15
        open_p = np.array([pl["p"] for pl in W.places if not pl["help"] and place_open(W, pl, m, ctx)]) if W.places else np.zeros((0, 2))
        help_p = [pl["p"] for pl in W.places if (pl["help"] or pl["pharm"]) and place_open(W, pl, m, ctx)] + [b["p"] for b in W.bart if W.bart_running(b, ctx.day, m)]
        n_open = W.count_edges_near(open_p, 0.5, 50); n_help = W.count_edges_near(np.array(help_p) if help_p else np.zeros((0, 2)), 0.5, 120)
        q = 0.45 * W.e_light + 0.35 * np.minimum(1.0, n_open / 3.0) + 0.20 * np.minimum(1.0, n_help)
        self._quick[k] = q; return q

    # ---------- routing ----------
    def _astar(self, a, b, weight):
        G = self.W.G; h = lambda u, v: float(np.hypot(*(G.nodes[u]["p"] - G.nodes[v]["p"])))
        return nx.astar_path(G, a, b, heuristic=h, weight=weight)

    def route(self, session, origin, dest, day, minute, emit: Emit = None, max_extra=0.25):
        with self.lock:
            t0 = time.time(); W = self.W; ctx = self.ctx(session, day, minute); say = emit or (lambda *a, **k: None)
            a, da = W.nearest_node(*origin); b, db = W.nearest_node(*dest)
            say("guide", "start", f"Planning {DAYS[day]} {minute // 60 % 24}:{minute % 60:02d}. Snapped to the street graph ({da:.0f} m and {db:.0f} m from your points).", {})
            q = self.quick(ctx); eidx = W.e_index
            paths = {}; paths["fast"] = self._astar(a, b, "length")
            for lam in (1, 2, 4, 8):
                w = {(u, v): d["length"] * (1 + lam * (1 - q[eidx[frozenset((u, v))]])) for u, v, d in W.G.edges(data=True)}
                nx.set_edge_attributes(W.G, w, f"w{lam}"); paths[f"l{lam}"] = self._astar(a, b, f"w{lam}")
            for seed in range(6):                      # seeded perturbations of the quality-weighted cost give genuinely different alternatives
                rng = np.random.default_rng(seed)
                jit = rng.uniform(0.7, 1.6, len(W.edges))
                w = {(u, v): d["length"] * (1 + 3 * (1 - q[eidx[frozenset((u, v))]])) * jit[eidx[frozenset((u, v))]] for u, v, d in W.G.edges(data=True)}
                nx.set_edge_attributes(W.G, w, "wj"); paths[f"j{seed}"] = self._astar(a, b, "wj")
            uniq = {}; [uniq.setdefault(tuple(p), k) for k, p in paths.items()]
            say("guide", "step", f"Found {len(uniq)} distinct candidate routes. Scoring each at the minute you pass every block.", {"n": len(uniq), "why": "alternatives come from the quality-weighted search plus seeded perturbations"})
            N = self.norm(ctx, (W.G.nodes[a]["p"] + W.G.nodes[b]["p"]) / 2); ev = []
            for p in uniq:
                m = metrics(W, ctx, list(p)); sc, pts, comp = score(m, N); ev.append(dict(path=list(p), m=m, score=sc, pts=pts, comp=comp))
            fast = next(e for e in ev if e["path"] == paths["fast"]); limit = fast["m"]["minutes"] * (1 + max_extra)
            ok = [e for e in ev if e["m"]["minutes"] <= limit]; best = max(ok, key=lambda e: e["score"])
            near = [e for e in ev if e["m"]["minutes"] <= fast["m"]["minutes"] * 1.08]; balanced = max(near, key=lambda e: e["score"])
            say("guide", "done", f"Best route scores {best['score']} against {fast['score']} for the fastest, {best['m']['minutes'] - fast['m']['minutes']:+.1f} min. Longest empty stretch {fast['m']['gap_m']:.0f} m to {best['m']['gap_m']:.0f} m.",
                {"best": best["score"], "fast": fast["score"], "why": "scored every candidate at the minute you pass each block; picked the highest score within +25% walking time"})
            options = [self._pack("fast", "Fastest", fast, ctx)]
            if balanced["path"] not in (fast["path"], best["path"]): options.append(self._pack("balanced", "Balanced", balanced, ctx))
            if best["path"] != fast["path"]: options.append(self._pack("best", "Streetwise", best, ctx))
            out = dict(depart=dict(day=DAYS[day], minute=minute), recommended="best" if best is not fast else "fast", norm=dict(lo=N.lo, hi=N.hi),
                       routes=options, candidates=len(uniq), ms=round((time.time() - t0) * 1000))
            return out

    def _pack(self, rid, label, e, ctx):
        W, m = self.W, e["m"]; shops = []
        for idx, (d, off) in sorted(m["open_idx"].items(), key=lambda kv: kv[1][0]):
            pl = W.places[idx]; shops.append(dict(id=pl["id"], d=d, off=off, name=pl["name"], cat=pl["cat"], ll=pl["ll"], hours=pl["hours"]))
        return dict(id=rid, label=label, score=e["score"], points=e["pts"], weights=WEIGHTS, minutes=round(m["minutes"], 1), km=round(m["length"] / 1000, 2), places_open=m["n_open"],
                    gap=dict(m=round(m["gap_m"]), range=[round(x) for x in m["gap_range"]] if m["gap_range"] else None), light_pct=round(100 * m["light"]), main_pct=round(100 * m["main"]),
                    turns_per_km=round(m["tpk"], 1), outages_near=m["outages_near"], light_known_pct=round(100 * m["light_known"]), unknown_hours_nearby=m["unknown_hours"],
                    coords=[W.G.nodes[n]["ll"] for n in e["path"]], shops=shops, covered=[bool(x) for x in m["covered"][::3]], steps=self.steps(e["path"]))

    # ---------- map layers ----------
    def heat(self, session, day, minute, cell=90.0):
        ctx = self.ctx(session, day, minute); q = self.quick(ctx); W = self.W; cells = {}
        for k, m in enumerate(W.e_mid):
            key = (int(m[0] // cell), int(m[1] // cell)); c = cells.setdefault(key, [0.0, 0.0, 0.0, 0]); c[0] += m[0]; c[1] += m[1]; c[2] += q[k]; c[3] += 1
        return [[*W.proj.ll((c[0] / c[3], c[1] / c[3])), round(100 * c[2] / c[3])] for c in cells.values()]

    def places(self, session, day, minute):
        ctx = self.ctx(session, day, minute); out = []
        for pl in self.W.places:
            if not pl["name"]: continue
            o = place_open(self.W, pl, minute, ctx); unknown = pl["hours"] is None and not pl["help"] and pl["id"] not in ctx.overrides
            out.append([pl["id"], pl["ll"][0], pl["ll"][1], pl["name"], pl["cat"], -1 if unknown else int(o), int(pl["id"] in ctx.overrides)])
        return out

    def search(self, q, limit=8):
        """Offline search over named places, streets and landmarks in the cached city. Prefix matches rank first."""
        q = q.strip().lower()
        if len(q) < 2: return []
        if not hasattr(self, "_names"):
            streets = {}
            for k, (a, b, ed) in enumerate(self.W.edges):
                if ed["name"]: streets.setdefault(ed["name"], []).append(k)
            self._names = [(n.lower(), n, "Landmark", [lo, la]) for n, la, lo in LANDMARKS]
            self._names += [(pl["name"].lower(), pl["name"], pl["cat"].replace("_", " ").title(), pl["ll"]) for pl in self.W.places if pl["name"]]
            for n, ks in streets.items():
                mid = self.W.e_mid[ks[len(ks) // 2]]; self._names.append((n.lower(), n, "Street", self.W.proj.ll(mid)))
        scored = []
        for low, name, kind, ll in self._names:
            if q in low:
                scored.append((0 if low.startswith(q) else 1, 0 if kind == "Landmark" else 1 if kind == "Street" else 2, len(low), name, kind, ll))
        scored.sort(); out, seen = [], set()
        for _, _, _, name, kind, ll in scored:
            key = (name.lower(), round(ll[0], 3), round(ll[1], 3))
            if key in seen: continue
            seen.add(key); out.append(dict(name=name, detail=kind, lon=ll[0], lat=ll[1]))
            if len(out) >= limit: break
        return out

    def landmarks(self): return [dict(name=n, lat=la, lon=lo) for n, la, lo in LANDMARKS]

    def meta(self):
        return dict(bbox=self.W.bbox, weights=WEIGHTS, stats=self.W.stats(), bart=[dict(name=b["name"], ll=b["ll"]) for b in self.W.bart], boot_seconds=self.boot_seconds)

    # ---------- place agents ----------
    def declare(self, session, place_id, until_minute, day, minute, emit: Emit = None):
        with self.lock:
            if place_id not in self.W.place_index: raise KeyError(place_id)
            pl = self.W.places[self.W.place_index[place_id]]; base = self.sessions.setdefault(session, Ctx(day, minute)); base.overrides[place_id] = until_minute
            (emit or (lambda *a, **k: None))("place", "step", f"{pl['name'] or pl['cat']} declares it is open until {until_minute // 60 % 24}:{until_minute % 60:02d}. Scores that pass it will be re-evaluated.", {"id": place_id})
            return dict(id=place_id, name=pl["name"], cat=pl["cat"], listed_hours=pl["hours"], until=until_minute)

    def clear(self, session): self.sessions.pop(session, None)

    def candidates_near(self, route_coords_m, limit=8):
        """Places near a route that are closed at the walk time and could plausibly stay open (what-if suggestions)."""
        return []

    def suggest_declarations(self, session, route, day, minute, limit=6):
        """Places inside a route's empty stretch that are currently closed and plausible late-night businesses. Used by the demo what-if."""
        with self.lock:
            W = self.W; ctx = self.ctx(session, day, minute); g = route["gap"]["range"]; out = []
            if not g: return out
            coords = route["coords"]; P = np.array([W.proj.xy(c[1], c[0]) for c in coords]); cum = np.r_[0, np.cumsum(np.hypot(*np.diff(P, axis=0).T))]
            for pl in W.places:
                if not pl["name"] or pl["cat"] not in LATE_OK or pl["help"] or pl["id"] in ctx.overrides: continue
                d = np.hypot(P[:, 0] - pl["p"][0], P[:, 1] - pl["p"][1]); j = int(d.argmin())
                if d[j] > 50 or not (g[0] - 30 <= cum[j] <= g[1] + 30): continue
                if place_open(W, pl, minute + cum[j] / WALK_SPEED / 60, ctx): continue
                out.append(dict(id=pl["id"], name=pl["name"], cat=pl["cat"], hours=pl["hours"], at=round(float(cum[j])), ll=pl["ll"]))
            return out[:limit]


    # ---------- turn-by-turn ----------
    def steps(self, path):
        """Group consecutive edges by street name and describe each maneuver. Distances are along the route in metres."""
        G = self.W.G; legs = []; cum = 0.0
        for i in range(len(path) - 1):
            d = G.edges[path[i], path[i + 1]]; name = d["name"] or "the path"
            if legs and legs[-1]["street"] == name: legs[-1]["len"] += d["length"]; legs[-1]["last"] = i
            else: legs.append(dict(street=name, at=cum, len=d["length"], first=i, last=i))
            cum += d["length"]
        out = []
        for k, lg in enumerate(legs):
            if k == 0: man = "start"
            else:
                a, b, c = (G.nodes[path[j]]["p"] for j in (lg["first"] - 1, lg["first"], lg["first"] + 1)); v1, v2 = b - a, c - b
                ang = math.degrees(math.atan2(v1[0] * v2[1] - v1[1] * v2[0], v1 @ v2)); mag = abs(ang)
                man = "continue" if mag < 25 else (("slight " if mag < 55 else "") + ("left" if ang > 0 else "right"))
            out.append(dict(street=lg["street"], maneuver=man, at_m=round(lg["at"]), len_m=round(lg["len"]), ll=G.nodes[path[lg["first"]]]["ll"]))
        return out

    # ---------- why this street ----------
    def why(self, session, lat, lon, day, minute):
        with self.lock:
            W = self.W; ctx = self.ctx(session, day, minute); p = W.proj.xy(lat, lon); d = np.hypot(W.e_mid[:, 0] - p[0], W.e_mid[:, 1] - p[1]); k = int(d.argmin())
            if d[k] > 80: return None
            a, b, ed = W.edges[k]; q = self.quick(ctx)[k]
            near = [pl for pl in W.places if np.hypot(*(pl["p"] - W.e_mid[k])) <= 60 + W.e_len[k] / 2]
            opened = [pl for pl in near if not pl["help"] and place_open(W, pl, minute, ctx)]; unknown = [pl for pl in near if pl["hours"] is None and not pl["help"]]
            lamps = int((np.hypot(W.lamps[:, 0] - W.e_mid[k][0], W.lamps[:, 1] - W.e_mid[k][1]) <= 40).sum()) if len(W.lamps) else 0
            outs = int((np.hypot(W.outages[:, 0] - W.e_mid[k][0], W.outages[:, 1] - W.e_mid[k][1]) <= 40).sum()) if len(W.outages) else 0
            hh = f"{(minute // 60) % 24 % 12 or 12}:{minute % 60:02d} {'PM' if (minute // 60) % 24 >= 12 else 'AM'}"
            text = (f"{len(opened)} place{'s' if len(opened) != 1 else ''} open within reach at {hh}" if opened else f"No listed place open here at {hh}")
            text += f"; {lamps} lamp location{'s' if lamps != 1 else ''} on record" + (f", {outs} open outage report{'s' if outs != 1 else ''}" if outs else "")
            if unknown: text += f". {len(unknown)} nearby place{'s have' if len(unknown) != 1 else ' has'} no listed hours and count as closed"
            return dict(street=ed["name"] or "Unnamed path", score=round(100 * float(q)), light_pct=round(100 * float(W.e_light[k])), open=[dict(name=pl["name"] or pl["cat"], hours=pl["hours"], src=pl.get("hours_source")) for pl in opened[:4]],
                        lamps=lamps, outages=outs, unknown_hours=len(unknown), ll=W.proj.ll(W.e_mid[k]), text=text)

    # ---------- darkness debt: where modeled walkers spend the most minutes on the weakest segments ----------
    def darkness_debt(self, day=4, minute=22 * 60 + 50, walkers=300, top=5, near=None):
        with self.lock:
            cell = Norm.cell_of(near) if near is not None else None; key = ("debt", day, minute // 30, cell)
            if key in self._quick: return self._quick[key]
            import random; W = self.W; ctx = Ctx(day, (minute // 30) * 30); q = self.quick(ctx); thresh = float(np.percentile(q, 25)); random.seed(5); cnt = {}
            h = lambda u, v: float(np.hypot(*(W.G.nodes[u]["p"] - W.G.nodes[v]["p"])))
            pool = range(len(W.nodes))
            if near is not None:                       # modeled walkers stay within about 2 km of the area being looked at
                cx, cy = (cell[0] + 0.5) * Norm.CELL, (cell[1] + 0.5) * Norm.CELL
                pool = [int(i) for i in np.where(np.hypot(W.node_p[:, 0] - cx, W.node_p[:, 1] - cy) <= 1.4 * Norm.CELL)[0]] or pool
            for _ in range(walkers):
                a, b = random.sample(pool, 2)
                if np.hypot(*(W.node_p[a] - W.node_p[b])) < 500: continue
                path = nx.astar_path(W.G, W.nodes[a], W.nodes[b], heuristic=h, weight="length")
                for u, v in zip(path, path[1:]):
                    i = W.e_index[frozenset((u, v))]
                    if q[i] < thresh: cnt[i] = cnt.get(i, 0.0) + W.e_len[i] / WALK_SPEED / 60
            by = {}
            for i, mins in cnt.items():
                nm = W.edges[i][2]["name"]
                if nm: by.setdefault(nm, [0.0, []]); by[nm][0] += mins; by[nm][1].append(i)
            rows = sorted(by.items(), key=lambda kv: -kv[1][0])[:top]
            out = [dict(street=n, minutes=round(m), segments=len(ix), ll=W.proj.ll(W.e_mid[ix[0]])) for n, (m, ix) in rows]
            res = dict(rows=out, walkers=walkers, note="Modeled walkers on uniform random trips, not measured foot traffic. Threshold: weakest quarter of segments."); self._quick[key] = res; return res

    # ---------- Watcher rules (deterministic; the model only phrases the message) ----------
    def watcher_decide(self, route, d, prev_d, stopped_s, since_checkin_s, replied):
        shops = route["shops"]; near = [s for s in shops if abs(s["d"] - d) <= 60]; gap = route["gap"]["range"]
        if replied: return dict(decision="ok", msg="Reply received. Continuing the walk.", why="you answered")
        if gap and prev_d is not None and prev_d < gap[0] <= d and stopped_s < 1:
            return dict(decision="info", msg=f"Entering {route['gap']['m']} m with no open place. Staying with you.", why="empty stretch ahead on the route")
        if since_checkin_s is None and stopped_s >= 90:
            if near:
                s = near[0]; return dict(decision="quiet", msg=f"Stopped near {s['name'] or s['cat']}, listed open. Staying quiet.", why=f"open place {s['off']} m away")
            return dict(decision="checkin", msg="You stopped. All good?", why="stopped 90 s on a segment with no open place within 60 m")
        if since_checkin_s is not None:
            if since_checkin_s >= 135: return dict(decision="escalate", msg="No answer. Alerting the guardian and preparing a handoff packet. I do not call 911.", why="standing order: guardian first, no emergency call")
            if since_checkin_s >= 45: return dict(decision="alert", msg="No reply in 45 s. Sending your live position to your guardian.", why="standing order: 45 s without an answer")
        return dict(decision="none", msg="", why="")

    def point_at(self, route, d):
        coords = route["coords"]; P = [self.W.proj.xy(c[1], c[0]) for c in coords]; tgt = max(0.0, min(d, route["km"] * 1000)); cum = 0.0
        for i in range(1, len(P)):
            L = float(np.hypot(*(P[i] - P[i - 1])))
            if cum + L >= tgt:
                t = (tgt - cum) / max(L, 1e-6); return [coords[i - 1][0] + (coords[i][0] - coords[i - 1][0]) * t, coords[i - 1][1] + (coords[i][1] - coords[i - 1][1]) * t]
            cum += L
        return coords[-1]

    # ---------- reverse geocoding from the street graph (offline) ----------
    def where(self, lat, lon):
        """Readable location for an alert: nearest named street and the cross streets either side, e.g. 'Howard St between 4th St and 5th St'."""
        with self.lock:
            W = self.W; p = W.proj.xy(lat, lon); d = np.hypot(W.e_mid[:, 0] - p[0], W.e_mid[:, 1] - p[1]); order = np.argsort(d)[:25]
            k = next((int(i) for i in order if W.edges[int(i)][2]["name"] and d[int(i)] <= 60), int(order[0]))
            a, b, ed = W.edges[k]; name = ed["name"]
            if not name: return dict(street=None, between=[], text="a walking path off the street grid", offset_m=round(float(d[k])))
            between = [c for c in (self._cross(a, b, name), self._cross(b, a, name)) if c]
            between = [short_street(c) for c in dict.fromkeys(between)]; name = short_street(name)
            text = f"{name} between {between[0]} and {between[1]}" if len(between) == 2 else f"{name} near {between[0]}" if between else name
            return dict(street=name, between=between, text=text, offset_m=round(float(d[k])))

    def _cross(self, node, prev, name, limit=60):
        G = self.W.G
        for _ in range(limit):
            other = [G.edges[node, n]["name"] for n in G.neighbors(node) if n != prev and G.edges[node, n]["name"] and G.edges[node, n]["name"] != name]
            if other: return other[0]
            nxt = [n for n in G.neighbors(node) if n != prev and G.edges[node, n]["name"] == name]
            if not nxt: return None
            prev, node = node, nxt[0]
        return None

    # ---------- open SF 311 streetlight cases (real case ids) ----------
    def cases_near(self, coords, radius=40.0, limit=10):
        """Open SF 311 streetlight cases within `radius` m of a [[lon, lat], ...] line, nearest first. Ids are the city's own case numbers."""
        W = self.W
        if not W.outage_cases or not coords: return []
        P = np.array([W.proj.xy(c[1], c[0]) for c in coords]); out = []
        for c in W.outage_cases:
            dist = float(np.min(np.hypot(P[:, 0] - c["p"][0], P[:, 1] - c["p"][1])))
            if dist <= radius: out.append(dict(id=c["id"], opened=c["opened"], details=c["details"], ll=c["ll"], meters=round(dist)))
        return sorted(out, key=lambda c: c["meters"])[:limit]

    def cases_on_street(self, name, radius=30.0, limit=5):
        W = self.W; mids = np.array([W.e_mid[i] for i, (_, _, ed) in enumerate(W.edges) if ed["name"] == name])
        if not len(mids) or not W.outage_cases: return []
        out = []
        for c in W.outage_cases:
            dist = float(np.min(np.hypot(mids[:, 0] - c["p"][0], mids[:, 1] - c["p"][1])))
            if dist <= radius: out.append(dict(id=c["id"], opened=c["opened"], details=c["details"], ll=c["ll"]))
        return sorted(out, key=lambda c: c["opened"], reverse=True)[:limit]

    def audit(self, route=None):
        W = self.W; miss = {}
        for pl in W.places:
            if pl["hours"] is None and not pl["help"]: miss[pl["cat"]] = miss.get(pl["cat"], 0) + 1
        top = sorted(miss.items(), key=lambda kv: -kv[1])[:5]
        return dict(places=len(W.places), no_hours=sum(miss.values()), top_missing=top, lamp_evidence=W.lamp_evidence, open_outages=len(W.outages),
                    near_route=route["unknown_hours_nearby"] if route else None)
