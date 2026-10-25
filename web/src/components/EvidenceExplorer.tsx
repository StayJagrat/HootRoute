import { useCallback, useEffect, useState } from 'react';
import { Button, Mascot } from './ui';
import { checkHours, errorText, planEvidence, type CheckRun, type EvidencePlace, type HoursCheck, type Plan, type PlanEvidence, type RouteKey, type Stats } from '../lib/api';
import { clockOfMinute, safeUrl, whenText } from '../lib/format';
import { PERSONA, SHORT } from '../lib/personas';
import './evidence.css';

const KIND: Record<EvidencePlace['evidence']['kind'], string> = {
  osm_tag: 'OpenStreetMap hours tag',
  listing_batch: 'Published listing (batch)',
  listing_live: 'Published listing (checked on request)',
  shopkeeper: 'Shopkeeper declaration',
  none: 'No published hours',
};

function OpenBadge({ v }: { v: boolean | null }) {
  if (v === true) return <span className="st-chip st-chip--ok">listed open at pass</span>;
  if (v === false) return <span className="st-chip">not listed open at pass</span>;
  return <span className="st-chip st-chip--info">hours unknown</span>;
}

/** Sherlock Hoots' evidence for every named place along the route: what hours were found, where, and when. */
export function EvidenceExplorer({ planId, route, apify, onPlan }: { planId: string; route: RouteKey; apify?: boolean; onPlan: (p: Plan) => void }) {
  const [id, setId] = useState(planId);
  const [ev, setEv] = useState<PlanEvidence | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [confirm, setConfirm] = useState(false);
  const [checking, setChecking] = useState(false);
  const [checkErr, setCheckErr] = useState<string | null>(null);
  const [result, setResult] = useState<HoursCheck | null>(null);

  useEffect(() => { setId(planId); }, [planId]);
  const load = useCallback(() => {
    setErr(null); setEv(null);
    planEvidence(id, route).then(setEv, (e) => setErr(errorText(e, 'Could not load the evidence.')));
  }, [id, route]);
  useEffect(load, [load]);

  // the server checks only places with unknown hours on this route, at most 6 per run (stale listed hours are flagged, not re-checked)
  const unknown = (ev?.places.filter((p) => p.openAtPass === null) ?? []).slice(0, 6);

  const run = async () => {
    setChecking(true); setCheckErr(null);
    try {
      const r = await checkHours(id, unknown.map((p) => p.id), true, route);
      setResult(r); setConfirm(false);
      if (r.planId && r.planId !== id) {
        if (r.plan) onPlan(r.plan);
        setId(r.planId);
      } else load();
    } catch (e) {
      setCheckErr(errorText(e, 'The check failed.'));
    } finally {
      setChecking(false);
    }
  };

  return (
    <div className="ev">
      {!ev && !err && <p className="t-caption">Loading the evidence for this route…</p>}
      {err && (
        <div className="plan__error" role="alert">
          {err} <button type="button" className="ev__retry" onClick={load}>Retry</button>
        </div>
      )}
      {ev && (
        <>
          <div className="ev__counts" aria-label="Evidence summary">
            <span><b className="t-mono">{ev.counts.listed}</b> listed</span>
            <span><b className="t-mono">{ev.counts.live}</b> checked on request</span>
            <span><b className="t-mono">{ev.counts.shopkeeper}</b> shopkeeper</span>
            <span><b className="t-mono">{ev.counts.unknown}</b> unknown</span>
            <span><b className="t-mono">{ev.counts.stale}</b> stale</span>
          </div>
          <p className="t-caption ev__note">Listed hours are published hours, not confirmation the place is staffed. Unknown hours stay unknown; they are never shown as closed.</p>

          {result && <CheckResult r={result} route={route} />}

          {unknown.length > 0 && !confirm && (
            <Button kind="secondary" block onClick={() => setConfirm(true)}>Check unknown hours · {unknown.length} place{unknown.length === 1 ? '' : 's'}</Button>
          )}
          {confirm && (
            <section className="ev__confirm" aria-label="Confirm hours check">
              <header><Mascot agent="checker" size={28} state="thinking" alt="" /><strong>{PERSONA.checker} asks first</strong></header>
              <p>{SHORT.checker} will look up the published listings for these places and nothing else:</p>
              <ul className="ev__names">{unknown.map((p) => <li key={p.id}>{p.name} <span className="t-caption">· passed at {clockOfMinute(p.passMinute)}</span></li>)}</ul>
              <p className="t-caption">This is a paid listing lookup. The server caps the cost of each check and the number of checks per day. Places checked recently are reused and not billed again.</p>
              {apify === false && <p className="ev__warn">Apify is not configured on this server. Any answer will come from the server's labelled test stand-in, not real listings.</p>}
              {checking && <p className="t-caption" role="status">{SHORT.checker} is reading the listings. This can take a minute.</p>}
              {checkErr && <p className="plan__error" role="alert">{checkErr}</p>}
              <div className="btn-row">
                <Button kind="secondary" onClick={() => setConfirm(false)} disabled={checking}>Cancel</Button>
                <Button kind="primary" onClick={() => void run()} disabled={checking}>{checking ? 'Checking…' : 'Run check'}</Button>
              </div>
            </section>
          )}

          <ul className="ev__list">
            {ev.places.map((p) => <PlaceCard key={p.id} p={p} />)}
            {ev.places.length === 0 && <li className="t-caption">No named places were found along this route. That data is missing, not zero.</li>}
          </ul>
        </>
      )}
    </div>
  );
}

function PlaceCard({ p }: { p: EvidencePlace }) {
  const url = safeUrl(p.evidence.url);
  return (
    <li className="ev__card">
      <div className="ev__top">
        <div className="ev__name">
          <strong>{p.name}</strong>
          <span className="t-caption">{p.cat} · passed at {clockOfMinute(p.passMinute)}</span>
        </div>
        <OpenBadge v={p.openAtPass} />
      </div>
      <div className="ev__hours t-mono">{p.hours ?? 'no published hours'}</div>
      <div className="ev__src">
        <span>{KIND[p.evidence.kind] ?? p.evidence.kind}</span>
        <span>· {p.evidence.provider}</span>
        {p.evidence.retrievedAt && <span>· {whenText(p.evidence.retrievedAt)}</span>}
        {p.evidence.stale && <span className="st-chip st-chip--warn">stale</span>}
        {url && <a href={url} target="_blank" rel="noopener noreferrer">source</a>}
      </div>
      {p.evidence.note && <p className="t-caption ev__pnote">{p.evidence.note}</p>}
    </li>
  );
}

function statsFor(s: Stats, route: RouteKey) {
  return route === 'fast' ? s.shortest : route === 'balanced' ? s.balanced ?? null : s.hootroute;
}

/** Before → after for one route, using only numbers the engine returned. */
export function BeforeAfter({ before, after, route }: { before: Stats; after: Stats; route: RouteKey }) {
  const b = statsFor(before, route), a = statsFor(after, route);
  if (!b || !a) return null;
  const row = (k: string, x: number, y: number, unit: string) => (
    <div className="ba__row"><span>{k}</span><span className="t-mono">{x}{unit}</span><span aria-hidden>→</span><span className={`t-mono${x !== y ? ' ba__chg' : ''}`}>{y}{unit}</span></div>
  );
  return (
    <div className="ba" aria-label="Before and after">
      <div className="ba__row ba__row--head"><span /><span>before</span><span /><span>after</span></div>
      {row('Score', b.score, a.score, '')}
      {row('Longest empty stretch', b.longestEmptyM, a.longestEmptyM, ' m')}
      {row('Minutes', Math.round(b.minutes * 10) / 10, Math.round(a.minutes * 10) / 10, '')}
    </div>
  );
}

/** What a listing check found, per place, with provenance. */
export function CheckResult({ r, route }: { r: CheckRun & Partial<Pick<HoursCheck, 'before' | 'after' | 'routeChanged'>>; route: RouteKey }) {
  const consoleLink = safeUrl(r.run?.consoleUrl);
  return (
    <section className="ev__result" role="status" aria-label="Check result">
      <header>
        <Mascot agent="checker" size={26} state="done" alt="" />
        <strong>Check result</strong>
        {r.mock && <span className="st-chip st-chip--warn">mock · test stand-in</span>}
      </header>
      {r.before && r.after && <BeforeAfter before={r.before} after={r.after} route={route} />}
      <p className="ev__line">
        {r.changed ? `${r.changed} place${r.changed === 1 ? '' : 's'} changed.` : r.ok ? 'No new hours found, so nothing changed.' : r.note}
        {r.routeChanged !== undefined && (r.routeChanged ? ' The recommended route changed.' : ' The recommended route stayed the same.')}
      </p>
      <ul className="ev__names">
        {r.results.map((x) => (
          <li key={x.id}><span className="st-chip">{x.status}</span> {x.name}{x.hours && x.hours !== 'off' ? <span className="t-mono"> {x.hours}</span> : null}</li>
        ))}
      </ul>
      <p className="t-caption">
        {typeof r.reused === 'number' && `${r.reused} reused from earlier evidence (not billed again). `}
        {r.run ? `${r.mock ? 'Test stand-in' : `Apify ${r.run.actor}`} · ${r.run.seconds} s · ${r.run.items} items` : ''}
        {r.run?.runId ? ` · run ${r.run.runId}` : ''}
        {consoleLink && <> · <a href={consoleLink} target="_blank" rel="noopener noreferrer">Apify console</a></>}
      </p>
      {r.note && <p className="t-caption">{r.note}</p>}
    </section>
  );
}
