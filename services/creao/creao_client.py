"""Run the Creao "Hours Detective" agent for places that still have no verified hours, and merge the answers into
data/cache/hours_evidence.json (the file the engine reads). API shape is from Creao's docs (agent.creao.ai); verify it with one run first.

    CREAO_API_KEY=capi_...  CREAO_AGENT_ID=...  python creao_client.py --limit 5 [--dry-run]

Runs take minutes and cost credits, so work in small batches (the demo corridor, 20 to 50 places). Results are validated before use.
"""
import argparse, json, os, sys, time
from datetime import datetime, timezone
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "data" / "cache"
sys.path.insert(0, str(ROOT / "services" / "engine"))
from streetwise_engine.world import World  # noqa: E402
sys.path.insert(0, str(ROOT / "services" / "hours"))
from hours_common import validate_osm_hours  # noqa: E402

BASE = "https://agent.creao.ai"


def load_env():
    for p in (ROOT / ".env", Path(__file__).parent / ".env"):
        if p.exists():
            for line in p.read_text().splitlines():
                if "=" in line and not line.strip().startswith("#"):
                    k, v = line.split("=", 1); os.environ.setdefault(k.strip(), v.split(" #")[0].strip().strip('"').strip("'"))


def call(method, path, key, body=None):
    req = urllib.request.Request(BASE + path, method=method, data=json.dumps(body).encode() if body else None, headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r: return json.loads(r.read())


def parse_json(text):
    s = text.strip(); a, b = s.find("{"), s.rfind("}")
    return json.loads(s[a:b + 1]) if a >= 0 and b > a else None


def valid(d, osm_id):
    if not d or d.get("osm_id") != osm_id: return False
    oh = d.get("opening_hours")
    if oh is None: return True
    ok, _ = validate_osm_hours(oh)
    if not ok: return False
    conf = d.get("confidence")
    if not isinstance(conf, (int, float)) or not 0.6 <= conf <= 1: return False
    sources = d.get("sources")
    return isinstance(sources, list) and any(
        isinstance(s, dict) and isinstance(s.get("url"), str) and s["url"].startswith(("https://", "http://"))
        and isinstance(s.get("quote"), str) and s["quote"].strip() for s in sources
    )


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--limit", type=int, default=5); ap.add_argument("--dry-run", action="store_true"); ap.add_argument("--wait", type=int, default=600)
    a = ap.parse_args(); load_env(); key, agent = os.environ.get("CREAO_API_KEY"), os.environ.get("CREAO_AGENT_ID")
    W = World(); f = CACHE / "hours_evidence.json"; ev = json.loads(f.read_text()) if f.exists() else {}
    todo = [pl for pl in W.places if pl["name"] and pl["hours"] is None and not pl["help"] and pl["id"] not in ev][: a.limit]
    print(f"{len(todo)} places to verify:", ", ".join(p["name"] for p in todo))
    if a.dry_run or not (key and agent):
        print("dry run (or CREAO_API_KEY / CREAO_AGENT_ID missing): nothing sent"); return
    runs = {}
    for pl in todo:
        inputs = dict(place_name=pl["name"], address="San Francisco, CA", lat=pl["ll"][1], lon=pl["ll"][0], osm_id=pl["id"], category=pl["cat"])
        r = call("POST", "/api/v1/runs", key, dict(appId=agent, inputs=inputs, idempotencyKey=pl["id"])); runs[pl["id"]] = r["id"]; print("started", pl["name"], r["id"])
    t0 = time.time(); pending = dict(runs)
    while pending and time.time() - t0 < a.wait:
        time.sleep(15)
        for oid, rid in list(pending.items()):
            r = call("GET", f"/api/v1/runs/{rid}", key)
            if r.get("status") in ("completed", "failed", "cancelled"):
                pending.pop(oid)
                d = parse_json((r.get("result") or {}).get("text") or "") if r["status"] == "completed" else None
                if valid(d, oid) and d.get("opening_hours"):
                    ev[oid] = dict(opening_hours=d["opening_hours"], confidence=d.get("confidence", 0.7), source="creao:hours_detective", fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"), raw=json.dumps(d.get("sources", []))[:500], run_id=rid)
                    print("ok  ", oid, d["opening_hours"], d.get("confidence"))
                else: print("skip", oid, r["status"], "(no verified hours)")
    f.write_text(json.dumps(ev, indent=1)); print(f"wrote {f} ({len(ev)} entries); still pending: {len(pending)}")


if __name__ == "__main__":
    main()
