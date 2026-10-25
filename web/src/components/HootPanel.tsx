import { useEffect, useRef, useState } from 'react';
import { Button, Mascot } from './ui';
import { CheckResult } from './EvidenceExplorer';
import { approveHead, askHead, errorText, type Approval, type HeadAnswer, type Health, type TraceEvent } from '../lib/api';
import { clockOfMinute } from '../lib/format';
import { PERSONA, SHORT } from '../lib/personas';
import { PREF_LABEL } from '../lib/prefs';
import { TOOL_LABEL, rememberMission } from './MissionControl';
import type { AgentName } from '../lib/types';
import './hoot.css';

interface Turn { id: number; q: string; a?: HeadAnswer; err?: string; kind: 'ask' | 'approve' | 'decline' }

const PROVIDER: Record<Approval['provider'], string> = {
  apify: 'Apify Google Maps listings',
  mock: 'Test stand-in (mock, not real listings)',
  unavailable: 'Unavailable on this server',
};

/** One line per agent that actually ran, in the order they ran. Written after the answer arrives. */
function whoDidWhat(trace: TraceEvent[]): { agent: AgentName; text: string }[] {
  const out: { agent: AgentName; tools: string[] }[] = [];
  for (const t of trace) {
    const label = (TOOL_LABEL[t.tool] ?? t.tool).toLowerCase();
    const last = out[out.length - 1];
    if (last && last.agent === t.agent) { if (!last.tools.includes(label)) last.tools.push(label); }
    else out.push({ agent: t.agent, tools: [label] });
  }
  return out.map((x) => ({ agent: x.agent, text: `${SHORT[x.agent]}: ${x.tools.join(', ')}` }));
}

/** Professor Hoot: ask in plain words. Paid checks wait for your approval. */
export function HootPanel({ health, onAnswer, onOpenMission, onOpenEvidence }: {
  health: Health | null;
  onAnswer: (a: HeadAnswer) => void;
  onOpenMission: (a: HeadAnswer) => void;
  onOpenEvidence?: () => void;
}) {
  const [text, setText] = useState('');
  const [turns, setTurns] = useState<Turn[]>([]);
  const [busy, setBusy] = useState<null | 'ask' | 'approve'>(null);
  const [resolved, setResolved] = useState<Record<string, 'approved' | 'declined'>>({});
  const [now, setNow] = useState(Date.now());
  const session = useRef<string | null>(null);
  const seq = useRef(0);

  const pending = [...turns].reverse().find((t) => t.a)?.a?.pendingApproval ?? null;
  const pendingOpen = pending && !resolved[pending.id];
  useEffect(() => {
    if (!pendingOpen) return;
    const t = window.setInterval(() => setNow(Date.now()), 5000);
    return () => window.clearInterval(t);
  }, [pendingOpen]);

  const land = (id: number, q: string, a: HeadAnswer) => {
    session.current = a.session;
    setTurns((ts) => ts.map((t) => (t.id === id ? { ...t, a } : t)));
    rememberMission({ question: q, by: a.by, ms: a.ms, trace: a.trace ?? [], at: Date.now() });
    onAnswer(a);
  };
  const fail = (id: number, e: unknown, fallback: string) => setTurns((ts) => ts.map((t) => (t.id === id ? { ...t, err: errorText(e, fallback) } : t)));

  const ask = async (q: string) => {
    const id = ++seq.current;
    setTurns((ts) => [...ts, { id, q, kind: 'ask' }]);
    setBusy('ask');
    try {
      land(id, q, await askHead(q, session.current, false));
    } catch (e) {
      fail(id, e, `${PERSONA.head} could not answer.`);
    } finally {
      setBusy(null);
    }
  };
  const decide = async (ap: Approval, approve: boolean) => {
    if (!session.current) return;
    const id = ++seq.current;
    const q = approve ? `Run the check on ${ap.places.length} place${ap.places.length === 1 ? '' : 's'}` : 'Not now';
    setTurns((ts) => [...ts, { id, q, kind: approve ? 'approve' : 'decline' }]);
    setBusy('approve');
    try {
      const a = await approveHead(session.current, ap.id, approve);
      setResolved((r) => ({ ...r, [ap.id]: approve ? 'approved' : 'declined' }));
      land(id, q, a);
    } catch (e) {
      fail(id, e, approve ? 'The check could not run.' : 'Could not reach Professor Hoot.');
      if ((e as { status?: number }).status === 404) setResolved((r) => ({ ...r, [ap.id]: 'declined' }));
    } finally {
      setBusy(null);
    }
  };

  const send = () => { const t = text.trim(); if (t && !busy) { setText(''); void ask(t); } };
  const shown = turns.slice(-2);
  const claudeOff = health?.claude === false;

  return (
    <section className="hoot" aria-label={`${PERSONA.head}, your assistant`}>
      <header className="hoot__head">
        <Mascot agent="head" state={busy ? 'thinking' : 'idle'} size={34} alt="" />
        <div className="hoot__who">
          <strong>{PERSONA.head}</strong>
          <span className="t-caption">{claudeOff ? 'Claude is unavailable on this server · answers come from the fixed pipeline' : 'Asks before any paid check'}</span>
        </div>
      </header>

      {turns.length > shown.length && <p className="t-caption hoot__older">{turns.length - shown.length} earlier question{turns.length - shown.length === 1 ? '' : 's'} in this conversation</p>}

      {shown.map((t) => (
        <div key={t.id} className="hoot__turn">
          <p className={`hoot__q${t.kind !== 'ask' ? ' hoot__q--action' : ''}`}>{t.q}</p>
          {!t.a && !t.err && <Working kind={t.kind} />}
          {t.err && (
            <div className="plan__error" role="alert">
              {t.err}
              {t.kind === 'ask' && <button type="button" className="ev__retry" disabled={!!busy} onClick={() => void ask(t.q)}>Retry</button>}
            </div>
          )}
          {t.a && <Answer a={t.a} onOpenMission={() => onOpenMission(t.a!)} onOpenEvidence={onOpenEvidence} />}
        </div>
      ))}

      {pending && pendingOpen && (
        <ApprovalCard ap={pending} now={now} busy={!!busy} onDecide={(ok) => void decide(pending, ok)} />
      )}

      <form className="head-ask" onSubmit={(e) => { e.preventDefault(); send(); }}>
        <input className="head-ask__input" value={text} onChange={(e) => setText(e.target.value)} maxLength={400} disabled={!!busy}
          placeholder="“Shift ends 11:30, Moscone to City Hall, fewer turns”" aria-label={`Ask ${PERSONA.head}`} />
        <button type="submit" className="head-ask__go" disabled={!!busy || !text.trim()}>{busy ? '…' : 'Ask'}</button>
      </form>
    </section>
  );
}

function Working({ kind }: { kind: Turn['kind'] }) {
  return (
    <p className="hoot__working t-caption" role="status">
      {kind === 'approve'
        ? `${SHORT.checker} is checking the approved listings. This can take a minute.`
        : kind === 'decline'
          ? `Telling ${SHORT.head} to skip the check…`
          : `${SHORT.head} is reading your request and choosing which agents to send…`}
    </p>
  );
}

function Answer({ a, onOpenMission, onOpenEvidence }: { a: HeadAnswer; onOpenMission: () => void; onOpenEvidence?: () => void }) {
  const prefs = a.preferences ? (Object.keys(PREF_LABEL) as (keyof typeof PREF_LABEL)[]).filter((k) => a.preferences?.[k]) : [];
  const lines = whoDidWhat(a.trace ?? []);
  return (
    <div className="hoot__a">
      <p className="hoot__text">{a.answer}</p>
      <div className="hoot__meta">
        <span className="t-caption">{a.by} · {(a.ms / 1000).toFixed(1)} s</span>
        {a.numbersCheck && (a.numbersCheck.ok
          ? <span className="st-chip st-chip--ok">Numbers verified against tool results</span>
          : <span className="st-chip st-chip--warn" title={a.numbersCheck.unverified.join(', ')}>Unverified numbers replaced with the engine summary</span>)}
      </div>
      {a.numbersCheck && !a.numbersCheck.ok && a.numbersCheck.unverified.length > 0 && (
        <p className="t-caption hoot__unv">Not found in any tool result: {a.numbersCheck.unverified.join(', ')}</p>
      )}
      {(prefs.length > 0 || a.preferences?.notes) && (
        <div className="hoot__prefs" aria-label="Preferences Professor Hoot understood">
          {prefs.map((k) => <span key={k} className="pref-chip pref-chip--on">{PREF_LABEL[k]}</span>)}
          {a.preferences?.notes && <span className="pref-chip">“{a.preferences.notes}”</span>}
        </div>
      )}
      {a.preferenceChoice?.reason && <p className="hoot__reason"><Mascot agent="guide" size={18} alt="" /> {a.preferenceChoice.reason}</p>}
      {a.check && <CheckResult r={{ ...a.check, before: a.before, after: a.after, routeChanged: a.routeChanged }} route="best" />}
      {lines.length > 0 && (
        <ul className="hoot__did">
          {lines.map((l, i) => <li key={i}><Mascot agent={l.agent} size={18} alt="" /> {l.text}</li>)}
        </ul>
      )}
      <div className="hoot__links">
        {(a.trace?.length ?? 0) > 0 && <button type="button" className="link-btn" onClick={onOpenMission}>Mission Control · {a.trace.length} tool call{a.trace.length === 1 ? '' : 's'}</button>}
        {onOpenEvidence && a.planId && <button type="button" className="link-btn" onClick={onOpenEvidence}>Evidence{a.evidence?.length ? ` · ${a.evidence.length} new` : ''}</button>}
      </div>
    </div>
  );
}

function ApprovalCard({ ap, now, busy, onDecide }: { ap: Approval; now: number; busy: boolean; onDecide: (ok: boolean) => void }) {
  const expired = ap.expiresAt > 0 && now > ap.expiresAt;
  const unavailable = ap.provider === 'unavailable';
  return (
    <section className="approval" aria-label="Approval needed">
      <header>
        <Mascot agent="checker" size={28} state="thinking" alt="" />
        <strong>Approve a listing check?</strong>
        <span className={`st-chip ${unavailable ? '' : ap.provider === 'mock' ? 'st-chip--warn' : 'st-chip--info'}`}>{ap.provider}</span>
      </header>
      <p className="approval__reason">{ap.reason}</p>
      <ul className="ev__names">
        {ap.places.map((p) => <li key={p.id}>{p.name} <span className="t-caption">· {p.cat} · passed at {clockOfMinute(p.passMinute)}</span></li>)}
      </ul>
      <dl className="approval__facts">
        <div><dt>Provider</dt><dd>{PROVIDER[ap.provider] ?? ap.provider}</dd></div>
        <div><dt>Max cost</dt><dd className="t-mono">${ap.maxUsd.toFixed(2)}</dd></div>
      </dl>
      {expired && <p className="ev__warn">This approval expired. Ask again to get a fresh one.</p>}
      {unavailable && <p className="t-caption">Listing checks are unavailable on this server, so nothing can be checked.</p>}
      <div className="btn-row">
        <Button kind="secondary" disabled={busy} onClick={() => onDecide(false)}>Not now</Button>
        <Button kind="primary" disabled={busy || unavailable || expired} onClick={() => onDecide(true)}>Run check</Button>
      </div>
    </section>
  );
}
