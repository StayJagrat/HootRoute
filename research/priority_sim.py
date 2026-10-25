"""Does repair order follow where people walk? Real 311 streetlight cases x modeled walker exposure.

Run after spike_score.py has cached data:  .venv/bin/python data/priority_sim.py
Exposure = number of 4,000 synthetic walkers (uniform random trips, shortest path) passing a segment. Modeled, not measured.
Counterfactual keeps the number of cases the city actually closed each day, but closes the highest-exposure open case first.
"""
import sys, json, random, collections
from datetime import datetime, timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import numpy as np, networkx as nx
import spike_score as S

CAP_DAYS = [None, 60, 30]
START, END = datetime(2025, 7, 1), datetime(2026, 10, 24)
P = lambda s: datetime.fromisoformat(s[:19])

def exposure(G, n=4000, seed=11):
    random.seed(seed); nodes = list(G.nodes); cnt = collections.Counter(); done = 0
    while done < n:
        a, b = random.sample(nodes, 2)
        if np.hypot(*(G.nodes[a]["p"] - G.nodes[b]["p"])) < 400: continue
        path = nx.shortest_path(G, a, b, weight="length"); done += 1
        for u, v in zip(path, path[1:]): cnt[frozenset((u, v))] += 1
    return cnt

def load_cases(G, cnt):
    edges = list(G.edges(data=True))
    mids = np.array([d["mid"] for _, _, d in edges]); expo = np.array([cnt[frozenset((a, b))] for a, b, _ in edges], float)
    S0, W0, N0, E0 = S.BBOX; cases = []
    for r in json.load(open(Path(__file__).parent / "cache/streetlights_since2023.json")):
        if not r.get("lat") or float(r["lat"]) == 0: continue  # ~15% of cases arrive with no location
        lat, lon = float(r["lat"]), float(r["long"])
        if not (S0 <= lat <= N0 and W0 <= lon <= E0): continue
        p = S.xy(lat, lon); d = np.hypot(mids[:, 0] - p[0], mids[:, 1] - p[1]); i = int(np.argmin(d))
        if d[i] > 60: continue
        cases.append(dict(t0=P(r["requested_datetime"]), t1=P(r["closed_date"]) if r.get("closed_date") else None, e=float(expo[i])))
    return cases

def days(a, b): return (b - a).total_seconds() / 86400

def simulate(sub):
    cap = collections.Counter(c["t1"].date() for c in sub if c["t1"] and c["t1"] <= END)
    pend = sorted(sub, key=lambda c: c["t0"]); i = 0; open_ = []; closed_at = {}; day = START.date()
    while day <= END.date():
        while i < len(pend) and pend[i]["t0"].date() <= day: open_.append(pend[i]); i += 1
        k = cap.get(day, 0)
        if k and open_:
            open_.sort(key=lambda c: -c["e"])
            for c in open_[:k]: closed_at[id(c)] = datetime.combine(day, datetime.min.time()) + timedelta(hours=12)
            open_ = open_[k:]
        day += timedelta(days=1)
    return closed_at

if __name__ == "__main__":
    G = S.build_graph(S.load_ways()); cnt = exposure(G); cases = load_cases(G, cnt)
    cl = [c for c in cases if c["t1"] and days(c["t0"], c["t1"]) >= 0]
    dur = np.array([days(c["t0"], c["t1"]) for c in cl]); ex = np.array([c["e"] for c in cl])
    print(f"{len(cases)} located cases in the pilot box; {len(cl)} closed. rank correlation (exposure, days to close) = {S.spearman(ex, dur):+.2f}")
    allx = np.sort([c["e"] for c in cases])[::-1]
    print(f"top 10% of case locations carry {allx[:len(allx)//10].sum() / allx.sum() * 100:.0f}% of modeled walker exposure")
    sub = [c for c in cases if START <= c["t0"] < END]; closed_at = simulate(sub)
    for cap in CAP_DAYS:
        f = (lambda d: d) if cap is None else (lambda d, cap=cap: min(d, cap))
        act = sum(c["e"] * f(days(c["t0"], c["t1"] or END)) for c in sub)
        cf = sum(c["e"] * f(days(c["t0"], closed_at.get(id(c)) or END)) for c in sub)
        print(f"cap {cap or 'none':>4} days: exposure-weighted dark days actual {act:>9,.0f} vs exposure-first {cf:>9,.0f}  -> {100 * (1 - cf / act):.0f}% less")
    still = [c for c in sub if not c["t1"]]
    print(f"{len(sub)} cases opened since {START.date()}; {len(still)} still open; exposure share of still-open cases: {sum(c['e'] for c in still)/sum(c['e'] for c in sub)*100:.0f}%")
