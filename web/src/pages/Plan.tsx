import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  approveHead, askHead, checkHours, createPlan, createWalk, errorText, gpsMode, health, planEvidence,
  type HeadAnswer, type Health, type Plan as LivePlan, type PlanEvidence, type RouteKey, type Spot, type TraceEvent,
} from '../lib/api';
import { loadPrefs, PREF_LABEL, savePrefs } from '../lib/prefs';
import { nameForPin, searchPlaces, type DestinationResult } from '../lib/search';
import type { Preferences } from '../lib/api';
import type { LngLat } from '../lib/types';
import { MapCanvas, type MapPlace } from '../Map';
import { ApprovalCard, CheckResult, type CheckView, Crew, EvidenceList, HootAnswer, minuteClock, ROUTE_NAME, RouteList, TraceList } from '../parts';
import type { AgentName } from '../lib/types';
import { Link } from 'react-router-dom';
import { Avatar } from '../Avatar';
import { Brand, Icon, Spinner, Toggle } from '../ui';

type When = { day: number; minute: number } | null;
const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const today = () => (new Date().getDay() + 6) % 7;
const nowMinute = () => new Date().getHours() * 60 + new Date().getMinutes();
const CHOICE: Record<RouteKey, 'hootroute' | 'usual' | 'balanced'> = { best: 'hootroute', fast: 'usual', balanced: 'balanced' };
const PREF_KEYS = ['fewerTurns', 'preferOpenPlaces', 'preferMainRoads', 'fastest', 'lowDistraction'] as const;

function PlaceField({ label, dot, value, onPick, onLocate }: { label: string; dot: string; value: Spot | null; onPick: (s: Spot) => void; onLocate?: () => void }) {
  const [q, setQ] = useState(value?.name ?? '');
  const [res, setRes] = useState<DestinationResult[]>([]);
  const [open, setOpen] = useState(false);
  useEffect(() => { setQ(value?.name ?? ''); }, [value]);
  useEffect(() => {
    if (!open || q.trim().length < 2 || q === value?.name) { setRes([]); return; }
    const ac = new AbortController();
    const t = setTimeout(() => void searchPlaces(q, ac.signal).then(setRes).catch(() => setRes([])), 220);
    return () => { clearTimeout(t); ac.abort(); };
  }, [q, open, value]);
  return (
    <div className="stack--tight">
      <label className="field">
        <span className="dot" style={{ background: dot }} />
        <span className="sr">{label}</span>
        <input value={q} placeholder={label} onChange={(e) => { setQ(e.target.value); setOpen(true); }} onFocus={() => setOpen(true)} onBlur={() => setTimeout(() => setOpen(false), 150)} />
        {onLocate && <button type="button" className="btn btn--quiet btn--sm" onClick={onLocate} aria-label="Use my location"><Icon name="locate" size={16} /></button>}
      </label>
      {open && res.length > 0 && (
        <div className="results">
          {res.map((r) => (
            <button key={`${r.name}${r.lngLat.join()}`} type="button" className="result" disabled={!r.covered} onMouseDown={(e) => e.preventDefault()}
              onClick={() => { onPick({ name: r.name, lngLat: r.lngLat }); setOpen(false); }}>
              {r.name}<small>{r.covered ? r.detail : `${r.detail} · outside San Francisco`}</small>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export default function Plan() {
  const nav = useNavigate();
  const [hp, setHp] = useState<Health | null>(null);
  const [from, setFrom] = useState<Spot | null>(null);
  const [to, setTo] = useState<Spot | null>(null);
  const [when, setWhen] = useState<When>(null);
  const [prefs, setPrefs] = useState<Preferences>(loadPrefs());
  const [text, setText] = useState('');
  const [session, setSession] = useState<string | null>(null);
  const [answer, setAnswer] = useState<HeadAnswer | null>(null);
  const [trace, setTrace] = useState<TraceEvent[]>([]);
  const [plan, setPlan] = useState<LivePlan | null>(null);
  const [planReq, setPlanReq] = useState<{ from: Spot; to: Spot; when: { day: number; minute: number } } | null>(null);
  const [pick, setPick] = useState<RouteKey>('best');
  const [tab, setTab] = useState<'routes' | 'evidence' | 'agents'>('routes');
  const [ev, setEv] = useState<PlanEvidence | null>(null);
  const [check, setCheck] = useState<CheckView | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [confirm, setConfirm] = useState(false);
  const [starting, setStarting] = useState(false);
  const ac = useRef<AbortController | null>(null);
  const [shown, setShown] = useState(0);            // how many real trace events the crew has replayed so far
  useEffect(() => {
    if (shown >= trace.length) return;
    const t = setTimeout(() => setShown((n) => n + 1), 420);
    return () => clearTimeout(t);
  }, [shown, trace.length]);
  const replaying = shown < trace.length;
  const current = replaying ? trace[shown] : null;
  const crewActive: AgentName | null = busy?.startsWith('Professor') ? 'head' : busy?.startsWith('Sherlock') ? 'checker' : busy?.startsWith('Scoot') ? 'guide' : current ? current.agent : null;
  const crewDone = useMemo(() => new Set(trace.slice(0, shown).map((e) => e.agent)), [trace, shown]);

  useEffect(() => { void health().then(setHp).catch(() => setHp(null)); }, []);
  useEffect(() => { savePrefs(prefs); }, [prefs]);
  const planId = plan?.planId ?? null;
  useEffect(() => {
    if (!planId) { setEv(null); return; }
    setEv(null);
    void planEvidence(planId, pick).then(setEv).catch(() => setEv(null));
  }, [planId, pick]);

  const adopt = (p: LivePlan, req: { from: Spot; to: Spot; when: { day: number; minute: number } }) => {
    setPlan(p); setPlanReq(req);
    const ids = (p.options ?? []).map((o) => o.id);
    const want = (p.preferenceChoice?.optionId ?? p.recommended ?? 'best') as RouteKey;
    setPick(ids.includes(want) ? want : (ids[0] as RouteKey) ?? 'best');
  };

  const planIt = async () => {
    if (!from || !to) return;
    ac.current?.abort(); ac.current = new AbortController();
    setBusy('Scoot McRoute is scoring every candidate route…'); setErr(null); setAnswer(null); setCheck(null);
    const w = when ?? { day: today(), minute: nowMinute() };
    try {
      const p = await createPlan(from, to, w, ac.current.signal, prefs);
      adopt(p, { from, to, when: w }); setTab('routes');
    } catch (e) { if ((e as Error).name !== 'AbortError') setErr(errorText(e, 'Could not plan this journey.')); }
    finally { setBusy(null); }
  };

  const take = (a: HeadAnswer) => {
    setAnswer(a); setSession(a.session); setTrace((t) => [...t, ...a.trace]);
    if (a.check) setCheck({ ...a.check, before: a.before, after: a.after, routeChanged: a.routeChanged });
    if (a.plan && a.planId && a.req) {
      const f: Spot = { name: a.req.origin.name, lngLat: [a.req.origin.lon, a.req.origin.lat] };
      const t: Spot = { name: a.req.destination.name, lngLat: [a.req.destination.lon, a.req.destination.lat] };
      setFrom(f); setTo(t); setWhen({ day: a.req.day, minute: a.req.minute });
      adopt({ ...(a.plan as LivePlan), planId: a.planId }, { from: f, to: t, when: { day: a.req.day, minute: a.req.minute } });
    }
  };

  const ask = async () => {
    const q = text.trim();
    if (!q) return;
    setBusy('Professor Hoot is choosing tools and delegating…'); setErr(null);
    try { take(await askHead(q, session)); setText(''); }
    catch (e) { setErr(errorText(e, 'Professor Hoot could not answer.')); }
    finally { setBusy(null); }
  };

  const answerApproval = async (yes: boolean) => {
    const ap = answer?.pendingApproval;
    if (!ap || !session) return;
    setBusy(yes ? 'Sherlock Hoots is checking published listings…' : null); setErr(null);
    try { take(await approveHead(session, ap.id, yes)); setTab(yes ? 'evidence' : tab); }
    catch (e) { setErr(errorText(e, 'The check could not run.')); }
    finally { setBusy(null); }
  };

  const investigate = async () => {
    if (!planId || !ev || !planReq) return;
    setConfirm(false); setBusy('Sherlock Hoots is checking published listings…'); setErr(null);
    try {
      const ids = ev.places.filter((p) => p.openAtPass === null).slice(0, 6).map((p) => p.id);
      const r = await checkHours(planId, ids, true, pick);
      setCheck(r);
      if (r.plan && r.planId !== planId) adopt(r.plan, planReq);
    } catch (e) { setErr(errorText(e, 'The check could not run.')); }
    finally { setBusy(null); }
  };

  const locate = () => {
    if (!navigator.geolocation) { setErr('This browser has no location. Type where you are instead.'); return; }
    navigator.geolocation.getCurrentPosition(
      async (p) => { const ll: LngLat = [p.coords.longitude, p.coords.latitude]; setFrom({ name: await nameForPin(ll), lngLat: ll }); },
      () => setErr('Location permission was denied. Type where you are instead.'),
      { enableHighAccuracy: true, timeout: 8000 },
    );
  };

  const reset = () => { setPlan(null); setPlanReq(null); setAnswer(null); setCheck(null); setEv(null); setErr(null); };
  const depart = planReq?.when.minute ?? nowMinute();
  const options = plan?.options ?? [];
  const routes = useMemo(() => options.map((o) => ({ id: o.id, coords: o.coords, active: o.id === pick })), [options, pick]);
  const places: MapPlace[] = useMemo(() => (ev?.places ?? []).map((p) => ({ id: p.id, lngLat: p.lngLat, state: p.openAtPass === null ? 'unknown' : p.openAtPass ? 'open' : 'closed' })), [ev]);
  const narrow = typeof window !== 'undefined' && window.innerWidth <= 760;
  const pending = answer?.pendingApproval && !check ? answer.pendingApproval : null;
  const whenLabel = (w: When) => (w ? `${DAYS[w.day]} ${minuteClock(w.minute)}` : 'Leaving now');

  return (
    <div className="app">
      <MapCanvas routes={routes} places={places} start={(plan ? planReq?.from : from)?.lngLat} end={(plan ? planReq?.to : to)?.lngLat}
        fitKey={`${planId}:${from?.lngLat}:${to?.lngLat}`} pad={narrow ? { left: 0, bottom: window.innerHeight * 0.62 } : { left: 420, bottom: 0 }}
        onTap={plan ? undefined : async (ll) => { const s = { name: await nameForPin(ll), lngLat: ll }; if (!from) setFrom(s); else setTo(s); }} />

      <section className={`panel ${plan ? 'panel--tall' : ''}`} aria-label="Journey">
        <header className="panel__head">
          <Link to="/" aria-label="HootRoute home" style={{ color: 'inherit', textDecoration: 'none' }}><Brand /></Link>
          {plan && <button className="btn btn--quiet btn--sm" onClick={reset}><Icon name="back" size={16} /> New journey</button>}
        </header>

        <div className="panel__body">
          {!plan && (
            <>
              <div className="stack--tight" style={{ marginTop: 10 }}>
                <Avatar id="head" state={text.trim() ? 'thinking' : 'idle'} size={52} />
                <h1 className="h1">Where to tonight?</h1>
                <p className="p">Routes compared by what is listed open, lit and running at the minute you pass each block. Conditions, not a safety rating.</p>
              </div>

              <div className="stack--tight">
                <label className="field" style={{ alignItems: 'flex-start' }}>
                  <span style={{ paddingTop: 14, color: 'var(--moon)' }}><Icon name="spark" size={16} /></span>
                  <span className="sr">Ask Professor Hoot</span>
                  <textarea rows={2} value={text} onChange={(e) => setText(e.target.value)} placeholder="Leaving the library at 11:40 PM, to Civic Center BART, fewer turns"
                    onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); void ask(); } }} />
                  <button className="btn btn--ghost btn--sm" style={{ marginTop: 7 }} disabled={!text.trim() || !!busy} onClick={() => void ask()}>Ask</button>
                </label>
                <span className="faint tiny">
                  Professor Hoot {hp?.claude ? 'runs on Claude tool use' : hp ? 'runs a fixed pipeline here (Claude is not configured)' : 'is offline'} · asks before any paid check
                </span>
              </div>

              <div className="row faint tiny" style={{ gap: 10 }}><hr className="rule" style={{ flex: 1 }} />or set it yourself<hr className="rule" style={{ flex: 1 }} /></div>

              <div className="stack--tight">
                <PlaceField label="From" dot="var(--fg)" value={from} onPick={setFrom} onLocate={locate} />
                <PlaceField label="To" dot="var(--moon)" value={to} onPick={setTo} />
                <span className="faint tiny">Or tap the map to drop a pin.</span>
              </div>

              <div className="stack--tight">
                <span className="eyebrow">Leaving</span>
                <div className="chips">
                  <button className="chip" aria-pressed={!when} onClick={() => setWhen(null)}>Now</button>
                  {[1380, 1410, 60].map((m) => {
                    const d = m < 300 ? (today() + 1) % 7 : today();
                    return <button key={m} className="chip" aria-pressed={when?.minute === m && when?.day === d} onClick={() => setWhen({ day: d, minute: m })}>{m < 300 ? 'After midnight' : 'Tonight'} {minuteClock(m)}</button>;
                  })}
                </div>
                <div className="row">
                  <label className="field" style={{ flex: 1 }}>
                    <span className="sr">Day</span>
                    <select value={when?.day ?? today()} onChange={(e) => setWhen({ day: Number(e.target.value), minute: when?.minute ?? nowMinute() })}>
                      {DAYS.map((d, i) => <option key={d} value={i}>{d}</option>)}
                    </select>
                  </label>
                  <label className="field" style={{ flex: 1 }}>
                    <span className="sr">Time</span>
                    <input type="time" value={`${String(Math.floor((when?.minute ?? nowMinute()) / 60)).padStart(2, '0')}:${String((when?.minute ?? nowMinute()) % 60).padStart(2, '0')}`}
                      onChange={(e) => { const [h, m] = e.target.value.split(':').map(Number); if (!Number.isNaN(h)) setWhen({ day: when?.day ?? today(), minute: h * 60 + (m || 0) }); }} />
                  </label>
                </div>
              </div>

              <div className="stack--tight">
                <span className="eyebrow">What matters</span>
                <div className="chips">
                  {PREF_KEYS.map((k) => <button key={k} className="chip" aria-pressed={prefs[k]} onClick={() => setPrefs({ ...prefs, [k]: !prefs[k] })}>{PREF_LABEL[k]}</button>)}
                </div>
              </div>
            </>
          )}

          {plan && planReq && (
            <>
              <div className="stack--tight" style={{ marginTop: 6 }}>
                <span className="eyebrow">{whenLabel(planReq.when)}</span>
                <h2 className="h2">{planReq.from.name} <span className="faint">→</span> {planReq.to.name}</h2>
              </div>
              {(busy || replaying || trace.length > 0) && (
                <div className="card stack--tight">
                  <Crew active={crewActive} done={crewDone} />
                  <span className="faint tiny" aria-live="polite">
                    {busy ?? (current ? `${current.persona}: ${current.tool.replace(/_/g, ' ')} · ${current.summary}` : `${trace.length} real tool calls · replayed from the trace`)}
                  </span>
                </div>
              )}
              {answer && !replaying && <HootAnswer a={answer} />}
              {pending && <ApprovalCard ap={pending} busy={!!busy} onAnswer={(y) => void answerApproval(y)} />}
              {check && <CheckResult r={check} route={pick} />}

              <div className="tabs" role="tablist">
                {(['routes', 'evidence', 'agents'] as const).map((t) => (
                  <button key={t} role="tab" className="tab" aria-selected={tab === t} onClick={() => setTab(t)}>
                    {t === 'routes' ? 'Routes' : t === 'evidence' ? `Evidence${ev ? ` · ${ev.counts.unknown} unknown` : ''}` : `Agents${trace.length ? ` · ${trace.length}` : ''}`}
                  </button>
                ))}
              </div>
              {tab === 'routes' && <RouteList options={options} pick={pick} onPick={setPick} depart={depart} recommended={plan.recommended} choiceReason={plan.preferenceChoice?.reason} />}
              {tab === 'evidence' && <EvidenceList ev={ev} busy={!!busy} onInvestigate={() => setConfirm(true)} />}
              {tab === 'agents' && <TraceList events={trace} shown={shown} />}

              <div className="stack--tight">
                <label className="field" style={{ alignItems: 'flex-start' }}>
                  <span style={{ paddingTop: 14, color: 'var(--moon)' }}><Icon name="spark" size={16} /></span>
                  <span className="sr">Ask a follow-up</span>
                  <textarea rows={1} value={text} onChange={(e) => setText(e.target.value)} placeholder="Ask Hoot: check the unknown hours · avoid Market St"
                    onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); void ask(); } }} />
                  <button className="btn btn--ghost btn--sm" style={{ marginTop: 7 }} disabled={!text.trim() || !!busy} onClick={() => void ask()}>Ask</button>
                </label>
              </div>
            </>
          )}

          {busy && !plan && <><Crew active={crewActive} done={crewDone} /><Spinner label={busy} /></>}
          {err && <p className="error" role="alert">{err}</p>}
        </div>

        <footer className="panel__foot">
          {!plan
            ? <button className="btn btn--primary btn--block" disabled={!from || !to || !!busy} onClick={() => void planIt()}>Compare routes <Icon name="arrow" size={16} /></button>
            : <button className="btn btn--primary btn--block" disabled={!!busy} onClick={() => setStarting(true)}>Start with {ROUTE_NAME[pick]} <Icon name="arrow" size={16} /></button>}
        </footer>
      </section>

      {confirm && ev && (
        <div className="overlay" role="dialog" aria-modal="true" aria-label="Confirm listing check">
          <div className="dialog">
            <h2 className="h2">Check published listings?</h2>
            <p className="p small">Sherlock Hoots looks up these places on Google Maps through Apify (one run, capped at $0.50), then Scoot re-scores the route.</p>
            <ul className="small" style={{ margin: 0, paddingLeft: 18 }}>
              {ev.places.filter((p) => p.openAtPass === null).slice(0, 6).map((p) => <li key={p.id}>{p.name}</li>)}
            </ul>
            {!hp?.apify && <p className="tiny" style={{ color: 'var(--amber)', margin: 0 }}>Apify is not configured on this server, so the check will report that and change nothing.</p>}
            <div className="row"><button className="btn btn--primary" onClick={() => void investigate()}>Run check</button><button className="btn btn--quiet" onClick={() => setConfirm(false)}>Cancel</button></div>
          </div>
        </div>
      )}
      {starting && plan && planReq && <StartDialog onClose={() => setStarting(false)} onStart={async (o) => {
        const w = await createWalk({ planId: plan.planId, from: planReq.from, to: planReq.to, when: planReq.when, choice: CHOICE[pick], notifyConsent: false,
          walker: o.name, guardian: o.contact, thresholds: { stopSeconds: 90, replySeconds: 45, escalateSeconds: 90 }, replay: o.replay, timeScale: o.replay ? 6 : 1 });
        nav(`/walk?walk=${encodeURIComponent(w.walkId)}${o.replay ? '&gps=replay' : ''}`);
      }} />}
    </div>
  );
}

function StartDialog({ onClose, onStart }: { onClose: () => void; onStart: (o: { name: string; contact: string; replay: boolean }) => Promise<void> }) {
  const [name, setName] = useState('');
  const [contact, setContact] = useState('');
  const [replay, setReplay] = useState(gpsMode() === 'replay');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  return (
    <div className="overlay" role="dialog" aria-modal="true" aria-label="Start journey">
      <div className="dialog">
        <h2 className="h2">Start your journey</h2>
        <div className="row" style={{ gap: 12 }}><Avatar id="rescuer" state="talking" size={44} /><p className="p small" style={{ margin: 0 }}>Wingman Wally follows the route, checks in if you stop where nothing is listed open, and takes your reports. Sharing is optional and you can stop it any time.</p></div>
        <label className="field"><span className="sr">Your name</span><input value={name} onChange={(e) => setName(e.target.value)} placeholder="Your first name (optional)" /></label>
        <label className="field"><span className="sr">Trusted contact</span><input value={contact} onChange={(e) => setContact(e.target.value)} placeholder="Trusted contact's name (optional)" /></label>
        <div className="between small"><span>Demo: replay GPS along the route <span className="faint">(labelled)</span></span><Toggle on={replay} onChange={setReplay} label="Replay GPS" /></div>
        <p className="faint tiny" style={{ margin: 0 }}>Share a live link with your contact from the journey screen if you want to. Nothing is texted or called. HootRoute never calls 911.</p>
        {err && <p className="error">{err}</p>}
        <div className="row">
          <button className="btn btn--primary" disabled={busy} onClick={async () => {
            setBusy(true); setErr(null);
            try { await onStart({ name: name.trim() || 'Walker', contact: contact.trim() || 'Trusted contact', replay }); }
            catch (e) { setErr(errorText(e, 'Could not start the journey.')); setBusy(false); }
          }}>{busy ? 'Starting…' : 'Start journey'}</button>
          <button className="btn btn--quiet" onClick={onClose}>Cancel</button>
        </div>
      </div>
    </div>
  );
}
