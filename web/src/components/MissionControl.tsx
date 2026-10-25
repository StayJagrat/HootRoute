import { useEffect, useState } from 'react';
import { Mascot } from './ui';
import { agents, type AgentInfo, type TraceEvent } from '../lib/api';
import { JOB, PERSONA } from '../lib/personas';
import type { AgentName } from '../lib/types';
import './mission.css';

export const TOOL_LABEL: Record<string, string> = {
  find_place: 'Find place',
  plan_routes: 'Plan and score routes',
  inspect_route: 'Inspect route',
  find_route_unknowns: 'Find unknown hours',
  propose_hours_check: 'Propose hours check',
  check_listed_hours: 'Check listed hours',
  rescore_routes: 'Re-score with evidence',
  replan_avoiding: 'Re-plan around a report',
  rank_by_preferences: 'Rank by your preferences',
};

const STATUS_LABEL: Record<TraceEvent['status'], string> = { ok: 'ok', error: 'error', needs_approval: 'needs approval', skipped: 'skipped' };

/** Group consecutive events that share a `group` number: those ran at the same time. */
function groups(trace: TraceEvent[]): TraceEvent[][] {
  const out: TraceEvent[][] = [];
  for (const t of trace) {
    const last = out[out.length - 1];
    if (last && t.group !== undefined && t.group !== null && last[0].group === t.group) last.push(t);
    else out.push([t]);
  }
  return out;
}

function json(v: unknown): string {
  try {
    return JSON.stringify(v, null, 2) ?? 'null';
  } catch {
    return String(v);
  }
}

/** Factual timeline of every real tool call behind one answer. Nothing here is animated or invented. */
export function TraceTimeline({ trace }: { trace: TraceEvent[] }) {
  if (!trace.length) return <p className="t-caption">No tools ran for this answer.</p>;
  const t0 = Math.min(...trace.map((t) => t.startedAt || 0).filter(Boolean)) || 0;
  return (
    <ol className="mc" aria-label="Agent tool calls">
      {groups(trace).map((g, i) => (
        <li key={g[0].id ?? i} className={`mc__step${g.length > 1 ? ' mc__step--parallel' : ''}`}>
          {g.length > 1 && <div className="mc__together t-caption">Ran at the same time · {g.length} calls</div>}
          <div className="mc__row">
            {g.map((t) => <TraceCard key={t.id} t={t} t0={t0} />)}
          </div>
        </li>
      ))}
    </ol>
  );
}

function TraceCard({ t, t0 }: { t: TraceEvent; t0: number }) {
  const persona = t.persona || PERSONA[t.agent] || t.agent;
  return (
    <article className={`mc__card mc__card--${t.status}`}>
      <header className="mc__head">
        <Mascot agent={t.agent} size={26} state={t.status === 'needs_approval' ? 'thinking' : 'idle'} alt="" />
        <div className="mc__who">
          <strong>{persona}</strong>
          <span className="t-caption">{TOOL_LABEL[t.tool] ?? t.tool}</span>
        </div>
        <span className={`st-chip st-chip--${t.status}`}>{STATUS_LABEL[t.status] ?? t.status}</span>
      </header>
      {t.why && <p className="mc__why"><span>why</span> {t.why}</p>}
      <p className="mc__sum">{t.summary}</p>
      <footer className="mc__foot t-mono">
        <span>{t.ms} ms</span>
        {t0 > 0 && t.startedAt > 0 && <span>start +{((t.startedAt - t0) / 1000).toFixed(1)} s</span>}
      </footer>
      <details className="mc__input">
        <summary>Input</summary>
        <pre>{json(t.input)}</pre>
      </details>
    </article>
  );
}

/** Who is on the crew and whether each one is live on this server (GET /api/agents). */
export function CrewStatus() {
  const [crew, setCrew] = useState<AgentInfo[] | null>(null);
  const [err, setErr] = useState(false);
  useEffect(() => {
    agents().then(setCrew, () => setErr(true));
  }, []);
  const ids: AgentName[] = ['head', 'guide', 'checker', 'rescuer'];
  return (
    <ul className="crew" aria-label="The crew">
      {ids.map((id) => {
        const a = crew?.find((x) => x.id === id);
        return (
          <li key={id} className="crew__item">
            <Mascot agent={id} size={30} alt="" />
            <div className="crew__text">
              <strong>{a?.persona ?? PERSONA[id]}</strong>
              <span className="t-caption">{a?.runsOn ?? JOB[id].runsOn}</span>
            </div>
            {a ? (
              <span className={`st-chip ${a.live ? 'st-chip--ok' : 'st-chip--skipped'}`}>{a.live ? 'live' : 'unavailable'}</span>
            ) : (
              <span className="st-chip st-chip--skipped">{err ? 'status unknown' : '…'}</span>
            )}
          </li>
        );
      })}
    </ul>
  );
}

// ---------------------------------------------------------------- last mission on this device (Plan → Room)
export interface MissionRecord { question: string; by: string; ms: number; trace: TraceEvent[]; at: number }
const KEY = 'hootroute:lastMission';
export function rememberMission(m: MissionRecord) {
  try {
    localStorage.setItem(KEY, JSON.stringify(m));
  } catch {
    /* storage blocked */
  }
}
function readMission(): MissionRecord | null {
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as MissionRecord) : null;
  } catch {
    return null;
  }
}
export function useLastMission(): MissionRecord | null {
  const [m, setM] = useState(readMission);
  useEffect(() => {
    const f = (e: StorageEvent) => { if (e.key === KEY) setM(readMission()); };
    window.addEventListener('storage', f);
    return () => window.removeEventListener('storage', f);
  }, []);
  return m;
}
