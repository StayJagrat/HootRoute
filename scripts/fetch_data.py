"""Fetch and cache every external dataset the engine needs. Run once with network; the app then runs offline from data/cache.

    python scripts/fetch_data.py            # all
    python scripts/fetch_data.py --only osm # osm | 311 | bart

Overpass is slow and flaky, so the bbox is fetched in tiles, each tile is cached, and several mirrors are tried in turn.
"""
import argparse, json, sys, time
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "cache"; CACHE.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT / "services" / "engine"))
from streetwise_engine.config import BBOX, TILES  # noqa: E402

UA = {"User-Agent": "streetwise-calhacks/0.1 (hackathon project)", "Accept": "*/*"}
MIRRORS = ["https://overpass.private.coffee/api/interpreter", "https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter"]
WAYS = r'way["highway"~"^(pedestrian|residential|tertiary|secondary|primary|living_street|service|unclassified|path|steps|footway|tertiary_link|secondary_link|primary_link)$"]["footway"!~"sidewalk|crossing"]["access"!~"private|no"]["service"!~"driveway|parking_aisle"]'
POINTS = r'''(
 node["highway"="street_lamp"]; node["man_made"="surveillance"];
 nwr["shop"];
 nwr["amenity"~"^(restaurant|cafe|bar|pub|fast_food|pharmacy|bank|cinema|theatre|nightclub|police|fire_station|hospital|clinic|fuel|convenience)$"];
 node["highway"="bus_stop"]; node["railway"="tram_stop"];
)'''


def overpass(body, bbox, tag):
    f = CACHE / f"{tag}.json"
    if f.exists(): return json.loads(f.read_text())["elements"]
    s, w, n, e = bbox
    if body.lstrip().startswith("("):
        q = f"[out:json][timeout:170][bbox:{s},{w},{n},{e}];{body};out center tags;"
    else:
        q = f"[out:json][timeout:170][bbox:{s},{w},{n},{e}];{body};out geom;"
    for attempt in range(6):
        url = MIRRORS[attempt % len(MIRRORS)]
        try:
            t0 = time.time(); r = requests.post(url, data={"data": q}, headers=UA, timeout=200)
            if r.status_code == 200 and r.text.lstrip().startswith("{"):
                d = r.json(); f.write_text(json.dumps(d)); print(f"  {tag}: {len(d['elements'])} elements via {url.split('/')[2]} in {time.time()-t0:.0f}s", flush=True); return d["elements"]
            print(f"  {tag}: HTTP {r.status_code} from {url.split('/')[2]}, retrying", flush=True)
        except Exception as ex:
            print(f"  {tag}: {type(ex).__name__} from {url.split('/')[2]}, retrying", flush=True)
        time.sleep(5 * (attempt + 1))
    raise SystemExit(f"giving up on {tag}")


def merge(parts):
    seen, out = set(), []
    for el in parts:
        k = (el["type"], el["id"])
        if k not in seen: seen.add(k); out.append(el)
    return out


def osm():
    ways, pts = [], []
    for i, t in enumerate(TILES):
        print(f"tile {i+1}/{len(TILES)} {t}", flush=True)
        ways += overpass(WAYS, t, f"osm_ways_t{i}"); pts += overpass(POINTS, t, f"osm_points_t{i}")
    ways, pts = merge(ways), merge(pts)
    (CACHE / "osm_ways.json").write_text(json.dumps(ways)); (CACHE / "osm_points.json").write_text(json.dumps(pts))
    print(f"OSM done: {len(ways)} ways, {len(pts)} points", flush=True)


def sf311():
    s, w, n, e = BBOX
    f = CACHE / "sf311_history.json"; pilot = CACHE / "sf311_history_pilot.json"
    if f.exists() and not pilot.exists(): pilot.write_bytes(f.read_bytes())
    box = f"within_box(point_geom,{s},{w},{n},{e})"
    where = f"service_name='Streetlights' AND requested_datetime > '2020-01-01' AND {box}"
    sel = "service_request_id,requested_datetime,closed_date,status_description,service_details,lat,long"
    hist, page = [], 50000
    while True:                                 # page through the Socrata API (citywide is more than one page)
        r = requests.get("https://data.sf.gov/resource/vw6y-z8j6.json", params={"$select": sel, "$where": where, "$order": "service_request_id", "$limit": page, "$offset": len(hist)}, headers=UA, timeout=180)
        r.raise_for_status(); rows = r.json(); hist += rows
        if len(rows) < page: break
    f.write_text(json.dumps(hist)); print(f"311: {len(hist)} streetlight cases since 2020 in the box", flush=True)


def bart():
    f = CACHE / "bart_gtfs.zip"
    if not f.exists():
        r = requests.get("https://www.bart.gov/dev/schedules/google_transit.zip", headers=UA, timeout=90); r.raise_for_status(); f.write_bytes(r.content)
    print(f"BART GTFS: {f.stat().st_size/1024:.0f} KB", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--only", choices=["osm", "311", "bart"]); a = ap.parse_args()
    for name, fn in (("311", sf311), ("bart", bart), ("osm", osm)):
        if a.only in (None, name): fn()
