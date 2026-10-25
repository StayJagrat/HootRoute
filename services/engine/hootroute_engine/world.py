"""World: the street graph and every time-dependent input the score reads. Loaded once from data/cache (see scripts/fetch_data.py)."""
import csv, io, json, math, re, zipfile
from collections import defaultdict

import networkx as nx
import numpy as np

from .config import BBOX, CACHE

DAYS = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]
GTFS_COLS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
HELP_AMENITY = {"police", "fire_station", "hospital"}
LATE_OK = {"cafe", "restaurant", "bar", "pub", "fast_food", "convenience", "pharmacy", "nightclub"}


def day_minute(day: int, minute: float) -> tuple[int, int]:
    """Resolve an arrival minute relative to the departure weekday, including week rollover."""
    offset, local = divmod(math.floor(minute), 1440)
    return (day + offset) % 7, local


def public_entrance(place: dict) -> bool:
    """Only explicit public entrance evidence qualifies for help-point access credit."""
    denied = {"no", "private", "customers", "permit"}
    return (place.get("entrance") in {"yes", "main"}
            and place.get("access") not in denied and place.get("foot") not in denied)


class Proj:
    """Equirectangular projection to metres, fine at city scale."""
    def __init__(self, bbox):
        s, w, n, e = bbox; self.s, self.w, self.n, self.e = s, w, n, e
        self.mx = 111_320 * math.cos(math.radians((s + n) / 2)); self.my = 110_540

    def xy(self, lat, lon): return np.array([(lon - self.w) * self.mx, (lat - self.s) * self.my])
    def ll(self, p): return [round(self.w + float(p[0]) / self.mx, 6), round(self.s + float(p[1]) / self.my, 6)]


def is_open(spec, day_idx, minutes):
    """OSM opening_hours subset: '24/7', 'Mo-Fr 09:00-17:00; Sa 10:00-14:00', 'off'. Returns True, False or None (no listed hours)."""
    if not spec: return None
    spec = spec.strip()
    if spec == "24/7": return True
    result = None
    for rule in [r.strip() for r in spec.split(";") if r.strip()]:
        m = re.match(r"^((?:Mo|Tu|We|Th|Fr|Sa|Su|PH)[-,\w]*)?\s*(.*)$", rule)
        days_s, rest = (m.group(1) or "Mo-Su"), m.group(2).strip(); days = set()
        for part in days_s.split(","):
            if "-" in part and part[:2] in DAYS and part[3:5] in DAYS:
                a, b = DAYS.index(part[:2]), DAYS.index(part[3:5]); days |= {(a + i) % 7 for i in range(((b - a) % 7) + 1)}
            elif part[:2] in DAYS: days.add(DAYS.index(part[:2]))
        if rest in ("off", "closed"):
            if day_idx in days: result = False
            continue
        spans = re.findall(r"(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})", rest)
        if not spans: continue
        for h1, m1, h2, m2 in spans:
            s, e = int(h1) * 60 + int(m1), int(h2) * 60 + int(m2)
            if e > 1440:                      # e.g. Fr 16:30-26:00 runs until 02:00 the next day
                if (day_idx in days and minutes >= s) or ((day_idx - 1) % 7 in days and minutes < e - 1440): return True
            elif e <= s:
                if (day_idx in days and minutes >= s) or ((day_idx - 1) % 7 in days and minutes < e): return True
            elif day_idx in days and s <= minutes < e: return True
        if day_idx in days and result is None: result = False
    return result


class World:
    def __init__(self, bbox=BBOX):
        self.proj = Proj(bbox); self.bbox = bbox
        self._load_graph(); self._load_points(); self._load_311(); self._load_bart(); self._edge_static()

    # ---------- graph ----------
    def _load_graph(self):
        ways = json.loads((CACHE / "osm_ways.json").read_text(encoding="utf-8")); G = nx.Graph(); P = self.proj
        for wy in ways:
            if wy.get("type") != "way" or "geometry" not in wy: continue
            nodes, geom, tags = wy["nodes"], wy["geometry"], wy.get("tags", {})
            if tags.get("foot") in {"no", "private"} or tags.get("access") in {"no", "private"}: continue
            for i in range(len(nodes) - 1):
                a, b = nodes[i], nodes[i + 1]; pa, pb = P.xy(geom[i]["lat"], geom[i]["lon"]), P.xy(geom[i + 1]["lat"], geom[i + 1]["lon"])
                L = float(np.hypot(*(pa - pb)))
                if L < 1: continue
                G.add_node(a, p=pa, ll=[geom[i]["lon"], geom[i]["lat"]]); G.add_node(b, p=pb, ll=[geom[i + 1]["lon"], geom[i + 1]["lat"]])
                G.add_edge(a, b, length=L, mid=(pa + pb) / 2, name=tags.get("name", ""), lit=tags.get("lit"), hw=tags.get("highway"), way=wy["id"])
        self.G = G.subgraph(max(nx.connected_components(G), key=len)).copy()
        self.nodes = list(self.G.nodes); self.node_p = np.array([self.G.nodes[n]["p"] for n in self.nodes])

    # ---------- OSM points ----------
    def _load_points(self):
        pts = json.loads((CACHE / "osm_points.json").read_text(encoding="utf-8")); P = self.proj
        self.places, lamps, cams, bus = [], [], [], []
        for el in pts:
            lat = el.get("lat") or el.get("center", {}).get("lat"); lon = el.get("lon") or el.get("center", {}).get("lon")
            if lat is None: continue
            t = el.get("tags", {}); p = P.xy(lat, lon)
            if t.get("highway") == "street_lamp": lamps.append(p)
            elif t.get("man_made") == "surveillance": cams.append(p)
            elif t.get("highway") == "bus_stop" or t.get("railway") == "tram_stop": bus.append(p)
            elif t.get("shop") or t.get("amenity"):
                am = t.get("amenity", "")
                self.places.append(dict(id=f"{el['type'][0]}{el['id']}", p=p, ll=[round(lon, 6), round(lat, 6)], name=t.get("name"), cat=am or t.get("shop", "shop"),
                                        hours=t.get("opening_hours"), help=am in HELP_AMENITY, pharm=am == "pharmacy",
                                        entrance=t.get("entrance"), access=t.get("access"), foot=t.get("foot")))
        self.lamps_osm = np.array(lamps) if lamps else np.zeros((0, 2)); self.cams = np.array(cams) if cams else np.zeros((0, 2)); self.bus = np.array(bus) if bus else np.zeros((0, 2))
        self._apply_hours_evidence()
        self.place_p = np.array([pl["p"] for pl in self.places]); self.place_index = {pl["id"]: i for i, pl in enumerate(self.places)}

    def _apply_hours_evidence(self, min_conf=0.6):
        """Fill missing opening hours from data/cache/hours_evidence.json (Apify + Claude pipeline). Listed OSM hours always win."""
        f = CACHE / "hours_evidence.json"; self.hours_filled = 0
        for pl in self.places: pl["hours_source"] = "osm" if pl["hours"] else None
        if not f.exists(): return
        ev = json.loads(f.read_text(encoding="utf-8"))
        for pl in self.places:
            e = ev.get(pl["id"])
            if pl["hours"] is None and e and e.get("opening_hours") and e.get("confidence", 0) >= min_conf:
                pl["hours"] = e["opening_hours"]; pl["hours_source"] = e.get("source", "evidence"); pl["hours_conf"] = e.get("confidence"); pl["hours_at"] = e.get("fetched_at"); self.hours_filled += 1

    # ---------- SF 311 ----------
    def _load_311(self):
        rows = json.loads((CACHE / "sf311_history.json").read_text(encoding="utf-8")); P = self.proj; seen, lamps, out = set(), [], []; self.outage_cases = []
        from datetime import datetime, timedelta
        recent = (datetime.now() - timedelta(days=180)).strftime("%Y-%m-%d")
        for r in rows:
            if not r.get("lat") or float(r["lat"]) == 0: continue          # ~27% of cases arrive without coordinates
            p = P.xy(float(r["lat"]), float(r["long"])); k = (int(p[0] // 12), int(p[1] // 12))
            if k not in seen: seen.add(k); lamps.append(p)                  # a report proves a pole stood here
            if r.get("status_description") == "Open" and r["requested_datetime"][:10] >= recent:
                out.append(p); self.outage_cases.append(dict(id=r["service_request_id"], opened=r["requested_datetime"][:10], details=r.get("service_details") or "Streetlight", p=p,
                                                              ll=[round(float(r["long"]), 6), round(float(r["lat"]), 6)]))
        self.lamp_evidence = len(lamps)
        allp = list(self.lamps_osm) + lamps; self.lamps = np.array(allp) if allp else np.zeros((0, 2))
        self.outages = np.array(out) if out else np.zeros((0, 2)); self.n311 = len(rows)

    # ---------- BART ----------
    def _load_bart(self):
        z = zipfile.ZipFile(CACHE / "bart_gtfs.zip"); P = self.proj
        rd = lambda n: list(csv.DictReader(io.TextIOWrapper(z.open(n), encoding="utf-8-sig")))
        stops = {r["stop_id"]: r for r in rd("stops.txt")}; s0, w0, n0, e0 = self.bbox
        inbox = {sid for sid, r in stops.items() if r.get("stop_lat") and s0 <= float(r["stop_lat"]) <= n0 and w0 <= float(r["stop_lon"]) <= e0}
        svc = {col: {r["service_id"] for r in rd("calendar.txt") if r[col] == "1"} for col in GTFS_COLS}
        trip_svc = {r["trip_id"]: r["service_id"] for r in rd("trips.txt")}
        deps = {col: defaultdict(list) for col in GTFS_COLS}
        for r in csv.DictReader(io.TextIOWrapper(z.open("stop_times.txt"), encoding="utf-8-sig")):
            if r["stop_id"] not in inbox: continue
            sv = trip_svc.get(r["trip_id"]); h, m, _ = r["departure_time"].split(":"); t = int(h) * 60 + int(m)
            for col in GTFS_COLS:
                if sv in svc[col]: deps[col][r["stop_id"]].append(t)
        self.bart = []
        for sid in inbox:
            if not any(deps[c].get(sid) for c in GTFS_COLS): continue       # entrances and exits carry no departures
            self.bart.append(dict(id=sid, name=stops[sid].get("stop_name", "BART"), p=P.xy(float(stops[sid]["stop_lat"]), float(stops[sid]["stop_lon"])),
                                  ll=[float(stops[sid]["stop_lon"]), float(stops[sid]["stop_lat"])], deps={c: np.array(sorted(deps[c].get(sid, []))) for c in GTFS_COLS}))
        self.bart_p = np.array([b["p"] for b in self.bart]) if self.bart else np.zeros((0, 2))

    def bart_running(self, b, day_idx, minute, window=20):
        day_idx, minute = day_minute(day_idx, minute)
        # GTFS permits Friday departures such as 24:10. They belong to Friday's
        # service calendar even though the clock now reads Saturday 00:10.
        return any(bool(len(d) and np.any(np.abs(d + offset * 1440 - minute) <= window))
                   for offset in (-1, 0, 1)
                   for d in (b["deps"][GTFS_COLS[(day_idx + offset) % 7]],))

    def help_route_distances(self, place, path, distances):
        """Walking-graph distance to an explicitly mapped public entrance, never air distance alone.

        The map still does not establish staffing or that an entrance is open tonight.
        An entrance over 30 m from the walking graph gets no access credit.
        """
        if not public_entrance(place): return np.full(len(distances), np.inf)
        cache = getattr(self, "_help_access", None)
        if cache is None: self._help_access = cache = {}
        key = (place["id"], tuple(place["p"]))
        if key not in cache:
            delta = np.hypot(self.node_p[:, 0] - place["p"][0], self.node_p[:, 1] - place["p"][1])
            i = int(delta.argmin()); snap = float(delta[i])
            lengths = nx.single_source_dijkstra_path_length(self.G, self.nodes[i], cutoff=200, weight="length") if snap <= 30 else {}
            cache[key] = (snap, lengths)
        snap, lengths = cache[key]
        points = np.array([self.G.nodes[n]["p"] for n in path])
        along = np.r_[0.0, np.cumsum(np.hypot(*np.diff(points, axis=0).T))]
        edge = np.clip(np.searchsorted(along, distances, side="right") - 1, 0, len(path) - 2)
        left = np.array([lengths.get(path[i], np.inf) for i in edge]) + distances - along[edge]
        right = np.array([lengths.get(path[i + 1], np.inf) for i in edge]) + along[edge + 1] - distances
        return np.minimum(left, right) + snap

    # ---------- per-edge static features (do not depend on the time of day) ----------
    def _edge_static(self):
        E = list(self.G.edges(data=True)); self.edges = E
        mids = np.array([d["mid"] for _, _, d in E]); L = np.array([d["length"] for _, _, d in E]); self.e_mid, self.e_len = mids, L
        n_lamps = self.count_edges_near(self.lamps, 0.5, 25); n_out = self.count_edges_near(self.outages, 0.5, 40)
        lit = np.array([d["lit"] for _, _, d in E], dtype=object)
        light = np.minimum(1.0, n_lamps / (L / 40 + 1)); light = np.where(lit == "yes", np.maximum(light, 0.75), light); light = np.where(lit == "no", np.minimum(light, 0.15), light)
        light = np.where((n_lamps == 0) & (lit != "yes") & (lit != "no"), 0.35, light); light = np.maximum(0.0, light - 0.25 * n_out)
        self.e_mid, self.e_len, self.e_light = mids, L, light
        self.e_main = np.array([d["hw"] in {"primary", "secondary", "tertiary", "primary_link", "secondary_link", "tertiary_link"} for _, _, d in E], float)
        self.e_index = {frozenset((a, b)): i for i, (a, b, _) in enumerate(E)}

    def count_edges_near(self, pts, extra, base):
        """For every edge: how many of `pts` lie within base + extra * edge_length of its midpoint (uniform grid lookup)."""
        E = len(self.edges); out = np.zeros(E, int)
        if not len(pts): return out
        cell = 60.0; grid = defaultdict(list)
        for i, p in enumerate(pts): grid[(int(p[0] // cell), int(p[1] // cell))].append(i)
        for k in range(E):
            m = self.e_mid[k]; r = base + extra * self.e_len[k]; cx, cy = int(m[0] // cell), int(m[1] // cell); rr = int(r // cell) + 1
            idx = [j for dx in range(-rr, rr + 1) for dy in range(-rr, rr + 1) for j in grid.get((cx + dx, cy + dy), ())]
            if idx: out[k] = int((np.hypot(pts[idx, 0] - m[0], pts[idx, 1] - m[1]) <= r).sum())
        return out

    def nearest_node(self, lat, lon):
        p = self.proj.xy(lat, lon); d = np.hypot(self.node_p[:, 0] - p[0], self.node_p[:, 1] - p[1]); i = int(np.argmin(d))
        return self.nodes[i], float(d[i])

    def stats(self):
        return dict(segments=self.G.number_of_edges(), km=round(float(self.e_len.sum()) / 1000, 1), places=len(self.places), places_no_hours=sum(1 for p in self.places if p["hours"] is None), hours_filled=getattr(self, "hours_filled", 0),
                    lamp_points=len(self.lamps), lamp_evidence=self.lamp_evidence, open_outages=len(self.outages), bus_stops=len(self.bus), bart_stations=len(self.bart), cases_311=self.n311)
