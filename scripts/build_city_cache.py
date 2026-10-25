"""Build the citywide OSM cache from a BBBike San Francisco extract (no Overpass, works offline once downloaded).

    curl -L -o data/raw/SanFrancisco.osm.pbf https://download.bbbike.org/osm/bbbike/SanFrancisco/SanFrancisco.osm.pbf
    .venv-agents/bin/python scripts/build_city_cache.py          # needs `pip install osmium`

Writes data/cache/osm_ways.json and osm_points.json in the same shape the engine already reads (Overpass `out geom` / `out center tags`),
and data/cache/bbox.json for the whole city. The previous downtown-pilot files are kept as *_pilot.json.
"""
import json, re, shutil, sys
from pathlib import Path

import osmium

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "cache"
PBF = ROOT / "data" / "raw" / "SanFrancisco.osm.pbf"
CITY = (37.7080, -122.5180, 37.8330, -122.3550)  # south, west, north, east: the city of San Francisco, Presidio to Bayview

HIGHWAY = {"pedestrian", "residential", "tertiary", "secondary", "primary", "living_street", "service", "unclassified", "path", "steps", "footway",
           "tertiary_link", "secondary_link", "primary_link"}
AMENITY = {"restaurant", "cafe", "bar", "pub", "fast_food", "pharmacy", "bank", "cinema", "theatre", "nightclub", "police", "fire_station", "hospital", "clinic", "fuel", "convenience"}
S, W, N, E = CITY


def inside(lat, lon): return S <= lat <= N and W <= lon <= E


class Handler(osmium.SimpleHandler):
    def __init__(self):
        super().__init__(); self.ways, self.points = [], []

    def node(self, n):
        if not n.location.valid(): return
        lat, lon = n.location.lat, n.location.lon
        if not inside(lat, lon) or not n.tags: return
        t = {k: v for k, v in n.tags}
        keep = (t.get("highway") in ("street_lamp", "bus_stop") or t.get("man_made") == "surveillance" or t.get("railway") == "tram_stop"
                or "shop" in t or t.get("amenity") in AMENITY)
        if keep: self.points.append({"type": "node", "id": n.id, "lat": lat, "lon": lon, "tags": t})

    def way(self, w):
        t = {k: v for k, v in w.tags}
        hw = t.get("highway")
        try: pts = [(nd.ref, nd.lat, nd.lon) for nd in w.nodes]
        except osmium.InvalidLocationError: return
        if not pts: return
        if hw in HIGHWAY:
            if (re.match(r"sidewalk|crossing", t.get("footway", "")) or re.match(r"private|no", t.get("access", ""))
                    or re.match(r"driveway|parking_aisle", t.get("service", ""))): return
            if not any(inside(la, lo) for _, la, lo in pts): return
            self.ways.append({"type": "way", "id": w.id, "nodes": [p[0] for p in pts], "geometry": [{"lat": p[1], "lon": p[2]} for p in pts], "tags": t})
        elif "shop" in t or t.get("amenity") in AMENITY:
            la = sum(p[1] for p in pts) / len(pts); lo = sum(p[2] for p in pts) / len(pts)
            if inside(la, lo): self.points.append({"type": "way", "id": w.id, "center": {"lat": la, "lon": lo}, "tags": t})


def main():
    if not PBF.exists(): sys.exit(f"missing {PBF}; see the docstring for the download command")
    for name in ("osm_ways", "osm_points", "bbox"):
        src, dst = CACHE / f"{name}.json", CACHE / f"{name}_pilot.json"
        if src.exists() and not dst.exists(): shutil.copy(src, dst)
    h = Handler(); h.apply_file(str(PBF), locations=True)
    (CACHE / "osm_ways.json").write_text(json.dumps(h.ways)); (CACHE / "osm_points.json").write_text(json.dumps(h.points))
    (CACHE / "bbox.json").write_text(json.dumps(list(CITY)))
    print(f"{len(h.ways)} ways, {len(h.points)} points -> {CACHE}")


if __name__ == "__main__":
    main()
