import { useMemo, useState } from 'react';
import type { AreaView, PlaceState, RouteKey } from './lib/api';
import type { RouteOption } from './lib/types';
import { minuteClock, ROUTE_NAME } from './parts';

// Every number on this screen comes from the engine (route points) or /api/area (listed hours). Nothing is computed into a score here.

const STATE_COLOR: Record<PlaceState, string> = { open: 'var(--mint)', unknown: 'var(--amber)', closed: '#4a5263' };
const STATE_LABEL: Record<PlaceState, string> = { open: 'Listed open', unknown: 'Hours unknown', closed: 'Listed closed' };
const STATES: PlaceState[] = ['open', 'unknown', 'closed'];

const FACTORS: { key: string; label: string; what: string }[] = [
  { key: 'places', label: 'Places listed open', what: 'Places listed open within 50 m as you pass, per km, against typical walks nearby at this hour.' },
  { key: 'light', label: 'Street lighting', what: 'Share of the route near mapped street lamps, less open outage reports.' },
  { key: 'gaps', label: 'Short empty stretches', what: 'Longest stretch with nothing listed open. Shorter earns more.' },
  { key: 'help', label: 'Help points nearby', what: 'Open pharmacies, 24/7 places, police, fire, hospitals and running BART within 200 m.' },
  { key: 'main', label: 'Main roads', what: 'Share of the route on main streets.' },
  { key: 'transit', label: 'Transit running', what: 'Bus and BART stops near the route with service at that minute.' },
  { key: 'turns', label: 'Simple turns', what: 'Fewer turns per km earns more.' },
];

/** Route score as a ring: the one hero number on the dashboard. */
function ScoreRing({ score }: { score: number }) {
  const r = 46, c = 2 * Math.PI * r, f = Math.max(0, Math.min(1, score / 100));
  return (
    <svg viewBox="0 0 112 112" width="112" height="112" role="img" aria-label={`Route score ${score} of 100`} className="dash-ring">
      <circle cx="56" cy="56" r={r} fill="none" stroke="rgba(169,193,255,0.14)" strokeWidth="8" />
      <circle cx="56" cy="56" r={r} fill="none" stroke="var(--moon)" strokeWidth="8" strokeLinecap="round"
        strokeDasharray={`${c * f} ${c}`} transform="rotate(-90 56 56)" className="dash-ring__arc" style={{ ['--len' as string]: `${c}` }} />
      <text x="56" y="58" textAnchor="middle" dominantBaseline="middle" className="dash-ring__num">{Math.round(score)}</text>
      <text x="56" y="80" textAnchor="middle" className="dash-ring__of">of 100</text>
    </svg>
  );
}

function RouteCompare({ options, pick }: { options: RouteOption[]; pick: RouteKey }) {
  const order: RouteKey[] = ['best', 'balanced', 'fast'];
  const rows = [...options].sort((a, b) => order.indexOf(a.id) - order.indexOf(b.id));
  return (
    <div className="dash-compare">
      {rows.map((o) => (
        <div key={o.id} className="dash-compare__row" aria-current={o.id === pick}>
          <span className="dash-compare__name">{ROUTE_NAME[o.id]}</span>
          <span className="dash-track"><span className="dash-fill" style={{ width: `${o.stats.score}%`, background: o.id === pick ? 'var(--moon)' : '#5b6477' }} /></span>
          <span className="mono dash-compare__val">{Math.round(o.stats.score)}</span>
          <span className="faint tiny mono">{Math.round(o.stats.minutes)} min</span>
        </div>
      ))}
    </div>
  );
}

/** The seven weighted factors the engine adds into the score, as points earned of points possible. */
function FactorBars({ o }: { o: RouteOption }) {
  const [hover, setHover] = useState<string | null>(null);
  const rows = FACTORS.filter((f) => o.weights[f.key] !== undefined).map((f) => ({ ...f, pts: o.points[f.key] ?? 0, max: o.weights[f.key] }));
  const weakest = new Set([...rows].sort((a, b) => a.pts / a.max - b.pts / b.max).slice(0, 2).map((r) => r.key));
  const shown = rows.find((r) => r.key === hover);
  return (
    <div className="stack--tight">
      <div className="dash-factors" onMouseLeave={() => setHover(null)}>
        {rows.map((r) => (
          <button key={r.key} type="button" className="dash-factor" onMouseEnter={() => setHover(r.key)} onFocus={() => setHover(r.key)} onBlur={() => setHover(null)}
            aria-label={`${r.label}: ${r.pts} of ${r.max} points`}>
            <span className="dash-factor__label">{r.label}{weakest.has(r.key) && <span className="dash-tag">weakest</span>}</span>
            <span className="mono dash-factor__val">{r.pts.toFixed(1)}<span className="faint"> / {r.max}</span></span>
            <span className="dash-track dash-track--wide"><span className="dash-fill" style={{ width: `${(100 * r.pts) / r.max}%` }} /></span>
          </button>
        ))}
      </div>
      <p className="faint tiny dash-readout" aria-live="polite">{shown ? shown.what : 'Hover a factor to see what it measures. Points add up to the score.'}</p>
    </div>
  );
}

/** Open / unknown / closed around the point as one segmented meter. */
function StateMeter({ counts }: { counts: Record<PlaceState, number> }) {
  return (
    <div className="stack--tight">
      <div className="dash-meter" role="img" aria-label={STATES.map((s) => `${counts[s]} ${STATE_LABEL[s].toLowerCase()}`).join(', ')}>
        {STATES.filter((s) => counts[s] > 0).map((s) => (
          <span key={s} title={`${STATE_LABEL[s]}: ${counts[s]}`} className={`dash-meter__seg dash-meter__seg--${s}`} style={{ flexGrow: counts[s], background: STATE_COLOR[s] }} />
        ))}
      </div>
      <div className="dash-legend">
        {STATES.map((s) => (
          <span key={s}><i style={{ background: STATE_COLOR[s] }} />{STATE_LABEL[s]} <b className="mono">{counts[s]}</b></span>
        ))}
      </div>
    </div>
  );
}

function Categories({ rows }: { rows: AreaView['categories'] }) {
  const max = Math.max(1, ...rows.map((r) => r.open + r.unknown + r.closed));
  return (
    <div className="dash-cats">
      {rows.map((r) => {
        const total = r.open + r.unknown + r.closed;
        return (
          <div key={r.cat} className="dash-cat" title={`${r.cat}: ${r.open} open, ${r.unknown} unknown, ${r.closed} closed`}>
            <span className="dash-cat__name">{r.cat}</span>
            <span className="dash-cat__bar" style={{ width: `${(100 * total) / max}%` }}>
              {STATES.filter((s) => r[s] > 0).map((s) => <span key={s} style={{ flexGrow: r[s], background: STATE_COLOR[s] }} />)}
            </span>
            <span className="mono tiny dash-cat__n">{r.open}<span className="faint">/{total}</span></span>
          </div>
        );
      })}
    </div>
  );
}

/** How many places nearby are listed open from 6 PM to 3 AM, with the walker's minute marked. */
function EveningCurve({ pts, at }: { pts: AreaView['evening']; at: number }) {
  const W = 340, H = 120, L = 28, R = 8, T = 10, B = 22;
  const [hi, setHi] = useState<number | null>(null);
  const lo = pts[0]?.minute ?? 1080, up = pts[pts.length - 1]?.minute ?? 1620;
  const top = Math.max(4, Math.ceil(Math.max(...pts.map((p) => p.open)) / 10) * 10);
  const x = (m: number) => L + ((m - lo) / (up - lo)) * (W - L - R);
  const y = (v: number) => T + (1 - v / top) * (H - T - B);
  const line = pts.map((p, i) => `${i ? 'L' : 'M'}${x(p.minute).toFixed(1)},${y(p.open).toFixed(1)}`).join('');
  const area = `${line}L${x(up)},${y(0)}L${x(lo)},${y(0)}Z`;
  const atN = at < 360 ? at + 1440 : at;
  const atIdx = atN >= lo && atN <= up ? pts.reduce((b, p, i) => (Math.abs(p.minute - atN) < Math.abs(pts[b].minute - atN) ? i : b), 0) : null;
  const h = hi ?? atIdx;
  const move = (e: React.PointerEvent<SVGRectElement>) => {
    const box = e.currentTarget.getBoundingClientRect(); const mx = ((e.clientX - box.left) / box.width) * (W - L - R) + L;
    setHi(pts.reduce((b, p, i) => (Math.abs(x(p.minute) - mx) < Math.abs(x(pts[b].minute) - mx) ? i : b), 0));
  };
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="dash-curve" role="img" aria-label={`Places listed open nearby: ${pts.map((p) => `${minuteClock(p.minute)} ${p.open}`).join(', ')}`}>
      {[0, top / 2, top].map((v) => (
        <g key={v}><line x1={L} x2={W - R} y1={y(v)} y2={y(v)} stroke="var(--line)" /><text x={L - 6} y={y(v) + 3} textAnchor="end" className="dash-axis">{v}</text></g>
      ))}
      {[1080, 1260, 1440, 1620].map((m) => <text key={m} x={x(m)} y={H - 6} textAnchor="middle" className="dash-axis">{minuteClock(m).replace(':00', '')}</text>)}
      <path d={area} fill="var(--mint)" opacity="0.1" />
      <path d={line} fill="none" stroke="var(--mint)" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" className="dash-curve__line" />
      {atIdx !== null && <line x1={x(atN)} x2={x(atN)} y1={T} y2={y(0)} stroke="var(--moon)" strokeWidth="1" strokeDasharray="3 3" opacity="0.7" />}
      {h !== null && (
        <g>
          <line x1={x(pts[h].minute)} x2={x(pts[h].minute)} y1={T} y2={y(0)} stroke="var(--line-2)" />
          <circle cx={x(pts[h].minute)} cy={y(pts[h].open)} r="4.5" fill="var(--mint)" stroke="var(--panel-solid)" strokeWidth="2" />
          <text x={Math.min(W - R - 2, Math.max(L + 2, x(pts[h].minute)))} y={T + 2} textAnchor={x(pts[h].minute) > W - 90 ? 'end' : x(pts[h].minute) < L + 60 ? 'start' : 'middle'} className="dash-tip">
            {minuteClock(pts[h].minute)} · {pts[h].open} listed open{hi === null ? ' · you' : ''}
          </text>
        </g>
      )}
      <rect x={L} y={T} width={W - L - R} height={H - T - B} fill="transparent" onPointerMove={move} onPointerLeave={() => setHi(null)} />
    </svg>
  );
}

/** Compact area card for the planning form: what is around the picked spot right now. */
export function AreaSummary({ a, name }: { a: AreaView; name: string }) {
  return (
    <div className="card stack--tight dash-card">
      <div className="between"><span className="eyebrow">Around {name}</span><span className="faint tiny">{a.radius} m</span></div>
      <StateMeter counts={a.counts} />
      <span className="faint tiny">Map heat: street conditions (lamps, places listed open, help points). Unknown hours are unknown, not closed.</span>
    </div>
  );
}

export function Dashboard({ option, options, pick, area, focus, onFocus, names, depart, loading }: {
  option: RouteOption | undefined; options: RouteOption[]; pick: RouteKey; area: AreaView | null; focus: 'from' | 'to'; onFocus: (f: 'from' | 'to') => void;
  names: { from: string; to: string }; depart: number; loading: boolean;
}) {
  const open = useMemo(() => (area?.places ?? []).filter((p) => p.state === 'open').slice(0, 6), [area]);
  return (
    <div className="stack dash">
      {option && (
        <div className="card dash-card dash-hero">
          <ScoreRing score={option.stats.score} />
          <div className="stack--tight" style={{ minWidth: 0, flex: 1 }}>
            <span className="eyebrow">{ROUTE_NAME[pick]} route</span>
            <RouteCompare options={options} pick={pick} />
          </div>
        </div>
      )}

      {option && (
        <div className="card dash-card stack--tight">
          <div className="between"><span className="eyebrow">What the score is made of</span><span className="faint tiny">points</span></div>
          <FactorBars o={option} />
        </div>
      )}

      <div className="card dash-card stack--tight">
        <div className="between">
          <span className="eyebrow">Around</span>
          <div className="dash-seg" role="tablist" aria-label="Area">
            {(['from', 'to'] as const).map((f) => <button key={f} role="tab" aria-selected={focus === f} onClick={() => onFocus(f)}>{f === 'from' ? names.from : names.to}</button>)}
          </div>
        </div>
        {!area && <span className="faint tiny">{loading ? 'Reading listed hours around this spot…' : 'No area data.'}</span>}
        {area && (
          <>
            <div className="kpis">
              <div className="kpi"><span className="mono">{area.counts.open}</span><small>listed open at {minuteClock(depart)}</small></div>
              <div className="kpi"><span className="mono">{area.places.length}</span><small>named places in {area.radius} m</small></div>
              <div className="kpi"><span className="mono">{area.conditions ?? '–'}</span><small>street conditions (map heat)</small></div>
            </div>
            <StateMeter counts={area.counts} />
          </>
        )}
      </div>

      {area && area.categories.length > 0 && (
        <div className="card dash-card stack--tight">
          <div className="between"><span className="eyebrow">By kind of place</span><span className="faint tiny">open / total</span></div>
          <Categories rows={area.categories} />
        </div>
      )}

      {area && (
        <div className="card dash-card stack--tight">
          <div className="between"><span className="eyebrow">Listed open through the night</span><span className="faint tiny">dashed line = you</span></div>
          <EveningCurve pts={area.evening} at={depart} />
          <span className="faint tiny">Counts places with published hours only. Published hours are not proof a place is staffed.</span>
        </div>
      )}

      {area && (
        <div className="card dash-card stack--tight">
          <span className="eyebrow">Closest listed open</span>
          {open.length === 0 && <span className="faint tiny">Nothing with published hours is listed open here at {minuteClock(depart)}.</span>}
          <ul className="dash-list">
            {open.map((p) => (
              <li key={p.id}>
                <i style={{ background: 'var(--mint)' }} />
                <span className="dash-list__main">{p.name}<small>{p.cat}{p.hours ? ` · ${p.hours}` : ''}</small></span>
                <span className="mono tiny faint">{p.d} m</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      <p className="faint tiny">Conditions, not a safety rating. No crime data. Heat is the engine's per-street conditions value, not the route score.</p>
    </div>
  );
}
