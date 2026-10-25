import { useState } from 'react';
import type { ApifyRun, Approval, EvidencePlace, HeadAnswer, HoursCheck, PlanEvidence, RouteKey, Stats, TraceEvent } from './lib/api';
import { clock } from './lib/format';
import { PERSONA } from './lib/personas';
import type { RouteOption, TravelMode } from './lib/types';
import { Avatar } from './Avatar';
import type { AgentName } from './lib/types';
import { Agent, Icon } from './ui';

export const ROUTE_NAME: Record<RouteKey, string> = { fast: 'Fastest', balanced: 'Balanced', best: 'HootRoute' };

export function minuteClock(m: number) {
  const x = ((Math.round(m) % 1440) + 1440) % 1440;
  return clock(`${String(Math.floor(x / 60)).padStart(2, '0')}:${String(x % 60).padStart(2, '0')}`);
}
const safeUrl = (u?: string | null) => (u && /^https?:\/\//.test(u) ? u : null);

/** Candidate routes from the engine. Every number here is the engine's. */
export function RouteList({ options, pick, onPick, depart, recommended, choiceReason, travelMode = 'walk' }: {
  options: RouteOption[]; pick: RouteKey; onPick: (k: RouteKey) => void; depart: number; recommended?: string; choiceReason?: string | null; travelMode?: TravelMode;
}) {
  const order: RouteKey[] = ['best', 'balanced', 'fast'];
  const sorted = [...options].sort((a, b) => order.indexOf(a.id) - order.indexOf(b.id));
  return (
    <div className="stack">
      {sorted.map((o) => (
        <button key={o.id} type="button" className="route" aria-pressed={pick === o.id} onClick={() => onPick(o.id)}>
          <span className="route__name">
            {ROUTE_NAME[o.id]}
            {recommended === o.id && <span className="badge badge--moon">Recommended</span>}
          </span>
          <span className="route__min">{Math.round(o.stats.minutes)}<span className="faint" style={{ fontSize: 12 }}> min</span></span>
          <span className="route__meta">
            {travelMode === 'cycle' && o.modeConditions && <span>Bike lanes <b>{o.modeConditions.cyclewayPct}%</b></span>}
            <span>Score <b>{o.stats.score}</b></span>
            <span>Longest stretch with nothing listed open <b>{o.stats.longestEmptyM} m</b></span>
            <span>Listed open <b>{o.placesOpen}</b></span>
            {o.turnsPerKm !== undefined && <span>Turns/km <b>{o.turnsPerKm}</b></span>}
            <span>Arrive <b>{minuteClock(depart + o.stats.minutes)}</b></span>
          </span>
        </button>
      ))}
      {choiceReason && <p className="p small">{choiceReason}</p>}
      {travelMode === 'cycle' && <p className="p small">With "Prefer mapped bike lanes" on, the recommended ride is the one with the most mapped bike lanes; the score still describes open places, lighting and gaps.</p>}
      <p className="faint tiny">{travelMode === 'walk' ? 'Score compares this walk with typical walks nearby at the same hour.' : 'Score compares this journey with routes nearby for this travel mode at the same hour.'} Conditions, not a safety rating. No crime data.</p>
    </div>
  );
}

/** Professor Hoot's reply, with who produced it and whether its numbers matched the tools. */
export function HootAnswer({ a }: { a: HeadAnswer }) {
  const verified = a.numbersCheck?.ok !== false;
  return (
    <div className="card fade stack--tight">
      <div className="between">
        <Agent id="head" />
        <span className={`badge ${verified ? 'badge--mint' : 'badge--amber'}`}>{verified ? 'Numbers match tool results' : 'Replaced unverified numbers'}</span>
      </div>
      <p style={{ margin: 0, lineHeight: 1.55 }}>{a.answer}</p>
      <span className="faint tiny">{a.by} · {(a.ms / 1000).toFixed(1)} s · {a.trace.length} tool call{a.trace.length === 1 ? '' : 's'}</span>
    </div>
  );
}

/** A paid check Professor Hoot proposed. Nothing runs until the walker presses Run. */
export function ApprovalCard({ ap, busy, onAnswer }: { ap: Approval; busy: boolean; onAnswer: (yes: boolean) => void }) {
  const expired = ap.expiresAt < Date.now();
  const off = ap.provider === 'unavailable';
  return (
    <div className="card card--amber fade stack">
      <div className="between">
        <Agent id="checker" />
        <span className="badge badge--amber">Needs your OK</span>
      </div>
      <p style={{ margin: 0 }}>{ap.reason || 'Check the published listings of places on your route whose hours are unknown.'}</p>
      <ul className="small muted" style={{ margin: 0, paddingLeft: 18 }}>
        {ap.places.map((p) => <li key={p.id}>{p.name} <span className="faint">· passed {minuteClock(p.passMinute)}</span></li>)}
      </ul>
      <span className="faint tiny">
        {off ? 'Live listing checks are not configured on this server (no APIFY_TOKEN).' : ap.provider === 'mock' ? 'Offline test stand-in, not real listings.' : `Apify Google Maps listings · up to $${ap.maxUsd.toFixed(2)}`}
      </span>
      <div className="row">
        <button className="btn btn--primary btn--sm" disabled={busy || off || expired} onClick={() => onAnswer(true)}>{busy ? 'Checking…' : 'Run check'}</button>
        <button className="btn btn--quiet btn--sm" disabled={busy} onClick={() => onAnswer(false)}>Not now</button>
        {expired && <span className="faint tiny">Expired. Ask again.</span>}
      </div>
    </div>
  );
}

/** What actually executed, in order. Only events the gateway returned. */
export function TraceList({ events, shown = events.length }: { events: TraceEvent[]; shown?: number }) {
  if (!events.length) return <p className="p small">No agent activity yet. Ask Professor Hoot to see every tool call, why it ran and what it returned.</p>;
  const t0 = events[0].startedAt;
  return (
    <div className="trace">
      {events.slice(0, shown).map((e, i) => {
        const par = e.group !== undefined && events.some((x, j) => j !== i && x.group === e.group);
        return (
          <div key={e.id} className={`step step--${e.status} reveal`}>
            <span className="step__rail"><i /></span>
            <span className="step__title">{e.tool.replace(/_/g, ' ')} <span>· {e.persona || PERSONA[e.agent]}</span></span>
            <span className="step__ms">+{((e.startedAt - t0) / 1000).toFixed(1)}s · {e.ms} ms</span>
            {e.why && <span className="step__why">{e.why}</span>}
            <span className="step__sum">{e.summary}</span>
            {par && <span className="step__par">ran in parallel</span>}
            <details><summary>input</summary><pre>{JSON.stringify(e.input, null, 1)}</pre></details>
          </div>
        );
      })}
    </div>
  );
}

const EV_LABEL: Record<string, string> = { osm_tag: 'OpenStreetMap tag', listing_batch: 'Listing (overnight run)', listing_live: 'Listing (checked live)', shopkeeper: 'Shopkeeper, unverified', none: 'No hours published' };

function EvRow({ p }: { p: EvidencePlace }) {
  const state = p.openAtPass === null ? <span className="badge badge--amber">Unknown</span> : p.openAtPass ? <span className="badge badge--mint">Listed open</span> : <span className="badge">Not open</span>;
  const url = safeUrl(p.evidence.url);
  return (
    <div className="ev">
      <span className="ev__name">{p.name} <span className="faint small">· {p.cat.replace(/_/g, ' ')}</span></span>
      {state}
      <span className="ev__src">
        Passed {minuteClock(p.passMinute)} · {EV_LABEL[p.evidence.kind] ?? p.evidence.kind}
        {p.evidence.retrievedAt ? ` · ${new Date(p.evidence.retrievedAt).toLocaleString()}` : ''}
        {p.evidence.stale ? ' · stale' : ''}
        {url && <> · <a href={url} target="_blank" rel="noopener noreferrer">source</a></>}
      </span>
    </div>
  );
}

export function EvidenceList({ ev, onInvestigate, busy }: { ev: PlanEvidence | null; onInvestigate?: () => void; busy?: boolean }) {
  const [all, setAll] = useState(false);
  if (!ev) return <p className="p small">Loading the evidence for this route…</p>;
  const c = ev.counts;
  const rows = all ? ev.places : ev.places.slice(0, 8);
  return (
    <div className="stack">
      <div className="kpis">
        <div className="kpi"><span className="mono">{c.listed}</span><small>with listed hours</small></div>
        <div className="kpi"><span className="mono" style={{ color: 'var(--amber)' }}>{c.unknown}</span><small>unknown hours</small></div>
        <div className="kpi"><span className="mono">{c.live}</span><small>checked live</small></div>
      </div>
      {onInvestigate && c.unknown > 0 && (
        <button className="btn btn--ghost btn--block" disabled={busy} onClick={onInvestigate}><Icon name="search" size={16} /> Investigate unknown hours</button>
      )}
      <div>{rows.map((p) => <EvRow key={p.id} p={p} />)}</div>
      {ev.places.length > 8 && <button className="btn btn--quiet btn--sm" onClick={() => setAll(!all)}>{all ? 'Show fewer' : `Show all ${ev.places.length}`}</button>}
      <p className="faint tiny">Published hours are not proof a place is staffed when you pass. Unknown is unknown, never closed.</p>
    </div>
  );
}

/** Before → after from the engine, plus what the listing check found. */
export interface CheckView { results: HoursCheck['results']; note: string; changed?: number; mock?: boolean; run?: ApifyRun | null; reused?: number; before?: Stats; after?: Stats; routeChanged?: boolean }

export function CheckResult({ r, route }: { r: CheckView; route: RouteKey }) {
  const k = route === 'fast' ? 'shortest' : route === 'balanced' ? 'balanced' : 'hootroute';
  const b = r.before?.[k as keyof Stats], a = r.after?.[k as keyof Stats];
  const consoleUrl = safeUrl(r.run?.consoleUrl);
  return (
    <div className="card fade stack">
      <div className="between"><Agent id="checker" />{r.mock && <span className="badge badge--amber">Test stand-in</span>}</div>
      {b && a && (
        <div className="kpis">
          <div className="kpi"><span className="mono">{b.score} → {a.score}</span><small>score</small></div>
          <div className="kpi"><span className="mono">{b.longestEmptyM} → {a.longestEmptyM}</span><small>longest empty, m</small></div>
          <div className="kpi"><span className="mono">{b.minutes} → {a.minutes}</span><small>minutes</small></div>
        </div>
      )}
      <p className="p small" style={{ color: 'var(--fg)' }}>
        {r.changed ? `${r.changed} place${r.changed === 1 ? '' : 's'} gained published hours.` : 'Nothing new to apply, so the numbers did not change.'}
        {r.routeChanged !== undefined && (r.routeChanged ? ' The recommended route changed.' : ' The recommended route is the same.')}
      </p>
      <div className="stack--tight small">
        {r.results.map((x) => (
          <div key={x.id} className="between"><span>{x.name}</span><span className="faint mono tiny">{x.status}{x.hours && x.hours !== 'off' ? ` · ${x.hours}` : ''}</span></div>
        ))}
      </div>
      <span className="faint tiny">
        {r.reused ? `${r.reused} reused from an earlier check (no new charge). ` : ''}
        {r.run ? `${r.run.actor} · ${r.run.seconds} s` : ''}{r.run?.runId ? ` · run ${r.run.runId}` : ''}
        {consoleUrl && <> · <a href={consoleUrl} target="_blank" rel="noopener noreferrer">Apify console</a></>}
        {!r.run && r.note ? r.note : ''}
      </span>
    </div>
  );
}

const CREW: AgentName[] = ['head', 'guide', 'checker', 'rescuer'];
const CREW_JOB: Record<AgentName, string> = { head: 'orchestrates', guide: 'routes', checker: 'evidence', rescuer: 'journey' };

/** The four agents with who is working right now. `active` comes from the real trace being replayed (or Hoot while waiting). */
export function Crew({ active, done }: { active: AgentName | null; done: Set<AgentName> }) {
  return (
    <div className="crew" aria-label="Agent crew">
      {CREW.map((id) => (
        <div key={id} className={`crew__m ${active === id ? 'crew__m--on' : ''}`}>
          <Avatar id={id} state={active === id ? (id === 'head' ? 'thinking' : 'talking') : done.has(id) ? 'done' : 'idle'} size={40} />
          <span>{PERSONA[id].split(' ')[0] === 'Professor' ? 'Hoot' : PERSONA[id].split(' ')[0]}<br />{CREW_JOB[id]}</span>
        </div>
      ))}
    </div>
  );
}
