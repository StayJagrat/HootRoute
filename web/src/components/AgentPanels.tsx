import { useEffect, useState } from 'react';
import { Button, Mascot } from './ui';
import { errorText, inspectRoute, routeUnknowns, type HeadAnswer, type Inspection, type Plan, type RouteKey, type TraceStep, type UnknownPlace } from '../lib/api';
import { PERSONA } from '../lib/personas';
import { TOOL_LABEL as TOOL } from './MissionControl';
import { AGENT_LABEL } from '../lib/format';
import type { AgentName, DemoData } from '../lib/types';

const FACTOR: Record<string, string> = { places: 'Open places', gaps: 'Gaps between them', help: 'Help points', light: 'Mapped lighting', main: 'Main roads', transit: 'Transit running', turns: 'Simple directions' };

function clock(minute: number) {
  const h = Math.floor(minute / 60) % 24;
  return `${h % 12 || 12}:${String(minute % 60).padStart(2, '0')} ${h < 12 ? 'AM' : 'PM'}`;
}

/** Ask the Head in plain words. Claude delegates to the Guide and the Checker; the trace shows every real tool call. */
export function HeadAsk({ busy, onAsk }: { busy: boolean; onAsk: (text: string) => void }) {
  const [text, setText] = useState('');
  const send = () => { const t = text.trim(); if (t && !busy) onAsk(t); };
  return (
    <form className="head-ask" onSubmit={(e) => { e.preventDefault(); send(); }}>
      <Mascot agent="head" state={busy ? 'thinking' : 'idle'} size={30} />
      <input className="head-ask__input" value={text} onChange={(e) => setText(e.target.value)} maxLength={400} disabled={busy}
        placeholder="“Shift ends 11:30, Moscone to City Hall, more places open”" aria-label={`Ask ${PERSONA.head}`} />
      <button type="submit" className="head-ask__go" disabled={busy || !text.trim()}>{busy ? '…' : 'Ask'}</button>
    </form>
  );
}

export function HeadAnswerCard({ a }: { a: HeadAnswer }) {
  const [open, setOpen] = useState(false);
  return (
    <section className="card head-answer" aria-label="Answer from the Head">
      <header><Mascot agent="head" state="talking" size={28} /><strong>{PERSONA.head}</strong><span className="t-caption">{a.by} · {(a.ms / 1000).toFixed(1)} s</span></header>
      <p className="head-answer__text">{a.answer}</p>
      {a.trace.length > 0 && (
        <>
          <button type="button" className="head-answer__toggle t-caption" onClick={() => setOpen(!open)} aria-expanded={open}>
            {open ? 'Hide' : 'Show'} agent activity · {a.trace.length} tool call{a.trace.length === 1 ? '' : 's'}
          </button>
          {open && <ol className="trace">{a.trace.map((t, i) => <TraceRow key={i} t={t} />)}</ol>}
        </>
      )}
    </section>
  );
}

function TraceRow({ t }: { t: TraceStep }) {
  return (
    <li className={`trace__row${t.ok ? '' : ' trace__row--fail'}`}>
      <Mascot agent={t.agent} size={22} />
      <div>
        <div className="trace__head"><strong>{AGENT_LABEL[t.agent]}</strong> · {TOOL[t.tool] ?? t.tool} <span className="t-mono">{t.ms} ms</span></div>
        <div className="t-caption">{t.summary}</div>
      </div>
    </li>
  );
}

/** Sherlock Hoots' look at the chosen route before you leave: where the score comes from and which places have unknown hours.
 *  Checking those hours happens in the Evidence Explorer, after you confirm. */
export function CheckerCard({ plan, route, onOpenEvidence }: { plan: Plan | DemoData; route: RouteKey; onOpenEvidence?: () => void }) {
  const planId = 'planId' in plan ? plan.planId : null;
  const opt = plan.options?.find((o) => o.id === route) ?? plan.options?.[0];
  const [unknowns, setUnknowns] = useState<UnknownPlace[] | null>(null);
  const [total, setTotal] = useState<number | null>(null);
  const [ins, setIns] = useState<Inspection | null>(null);
  const [insErr, setInsErr] = useState<string | null>(null);
  const [why, setWhy] = useState(false);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    setIns(null); setInsErr(null);
    if (!planId) return;
    inspectRoute(planId, route).then(setIns).catch((e) => setInsErr(errorText(e, 'The route check failed.')));
  }, [planId, route, tick]);

  useEffect(() => {
    setUnknowns(null);
    if (!planId) return;
    routeUnknowns(planId).then((r) => { setUnknowns(r.places); setTotal(r.total); }).catch(() => setUnknowns([]));
  }, [planId, route]);

  const n = total ?? unknowns?.length ?? 0;
  return (
    <section className="card checker" aria-label={`Route check by ${PERSONA.checker}`}>
      <header><Mascot agent="checker" state={planId && !ins && !insErr ? 'thinking' : ins?.good ? 'done' : 'talking'} size={28} /><strong>{PERSONA.checker}</strong><span className="t-caption">walked the route before you</span></header>
      {planId && !ins && !insErr && <p className="t-caption">Walking the route on the map…</p>}
      {insErr && <p className="plan__error" role="alert">{insErr} <button type="button" className="ev__retry" onClick={() => setTick(tick + 1)}>Retry</button></p>}
      {ins && (
        <>
          <div className={`verdict${ins.good ? ' verdict--good' : ' verdict--heads'}`} role="status">{ins.good ? '✓ ' : ''}{ins.verdict}<small>score {ins.score}/100 · arrive {ins.arrive}</small></div>
          <ul className="inspect">
            {ins.items.map((x) => (
              <li key={x.title} className={`inspect__item inspect__item--${x.level}`}>
                <span className="inspect__dot" aria-label={x.level} />
                <div><strong>{x.title}</strong><div className="t-caption">{x.detail}</div><div className="inspect__src">{x.source}</div></div>
              </li>
            ))}
          </ul>
          {ins.missing.map((m) => <p key={m} className="t-caption inspect__missing">Data missing: {m}</p>)}
        </>
      )}
      {opt && <button type="button" className="head-answer__toggle t-caption" onClick={() => setWhy(!why)} aria-expanded={why}>{why ? 'Hide' : 'Show'} where the score comes from</button>}
      {opt && why && (
        <div className="checker__bars" role="list" aria-label="Where the score comes from">
          {Object.entries(opt.points).map(([k, v]) => (
            <div className="checker__bar" role="listitem" key={k}>
              <span>{FACTOR[k] ?? k}</span>
              <i style={{ ['--w' as string]: `${Math.round((v / (opt.weights[k] || 1)) * 100)}%` }} />
              <b className="t-mono">{Math.round(v)}/{opt.weights[k]}</b>
            </div>
          ))}
        </div>
      )}
      {!planId && <p className="t-caption">Simulated demo: live checks need the live gateway. This offline demo shows cached data only.</p>}
      {planId && unknowns === null && <p className="t-caption">Looking for places with unknown hours…</p>}
      {unknowns && unknowns.length === 0 && <p className="t-caption">Every named place on this route has published hours.</p>}
      {unknowns && unknowns.length > 0 && (
        <>
          <p className="checker__text">{n} place{n === 1 ? '' : 's'} along this route publish no hours. Their hours are unknown, so the score does not count them as open:</p>
          <ul className="checker__list">{unknowns.slice(0, 4).map((u) => <li key={u.id}>{u.name} <span className="t-caption">· passed at {clock(u.passMinute)}</span></li>)}</ul>
        </>
      )}
      {planId && onOpenEvidence && <Button kind="secondary" block onClick={onOpenEvidence}>{unknowns && unknowns.length > 0 ? 'Evidence · check unknown hours' : 'See the evidence'}</Button>}
    </section>
  );
}

const LADDER_DEFAULT = ['Live link to guardian (text only with your opt-in)', 'Call guardian (with your opt-in)', 'Text and call backup contact (with your opt-in)', 'Call 911 button for people (never automatic)'];

/** The Rescuer's escalation ladder: each rung waits for someone to answer before the next. */
export function RescueLadder({ ladder }: { ladder?: { step: number; status: string; steps: string[] } }) {
  const steps = ladder?.steps?.length ? ladder.steps : LADDER_DEFAULT;
  const at = ladder?.step ?? 0;
  const cleared = ladder?.status.startsWith('cleared');
  return (
    <ol className="ladder" aria-label="Rescue ladder">
      {steps.map((label, i) => (
        <li key={label} className={`ladder__rung${i < at || (i === at && cleared) ? ' ladder__rung--done' : i === at ? ' ladder__rung--now' : ''}`}>
          <span className="ladder__n">{i + 1}</span>
          <span>{label}{i === at && ladder ? <small> · {ladder.status}</small> : null}</span>
        </li>
      ))}
    </ol>
  );
}

/** A real phone link: the person decides. HootRoute never dials 911 on its own. */
export function Call911({ who }: { who?: string }) {
  return <a className="btn btn--help btn--block call911" href="tel:911">Call 911{who ? ` for ${who}` : ''}</a>;
}


/** The walk in four steps, one agent each. */
export function Steps({ at }: { at: 1 | 2 | 3 | 4 }) {
  const s: [AgentName, string][] = [['guide', 'Route'], ['checker', 'Check'], ['rescuer', 'Walk'], ['head', 'Report']];
  return (
    <ol className="steps" aria-label="Your walk in four steps">
      {s.map(([a, label], i) => (
        <li key={a} className={`steps__item${i + 1 === at ? ' on' : i + 1 < at ? ' done' : ''}`} aria-current={i + 1 === at ? 'step' : undefined}>
          <Mascot agent={a} size={18} state={i + 1 < at ? 'done' : 'idle'} /><span className="steps__n">{i + 1}</span>{i + 1}. {label}
        </li>
      ))}
    </ol>
  );
}
