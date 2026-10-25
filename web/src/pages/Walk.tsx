import { useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { errorText, gpsMode, setSharing, walkCreds } from '../lib/api';
import { watchLocation } from '../lib/device';
import { cumulative, project } from '../lib/geo';
import { PERSONA } from '../lib/personas';
import { GpsReplay } from '../lib/replay';
import { useWalk } from '../lib/store';
import type { AgentName, LngLat, ObstacleKind, RouteStep } from '../lib/types';
import { isMuted, setMuted, speak } from '../lib/voice';
import { MapCanvas } from '../Map';
import { minuteClock } from '../parts';
import { Agent, Brand, Icon, Toggle } from '../ui';

const KINDS: [ObstacleKind, string][] = [['blocked', 'Path blocked'], ['construction', 'Construction'], ['place_closed', 'Place closed'], ['want_detour', 'Different way'], ['other', 'Other']];
const nowMin = () => new Date().getHours() * 60 + new Date().getMinutes();

function nextTurn(steps: RouteStep[], meters: number) {
  const s = steps.find((x) => x.at_m > meters + 5 && /left|right/.test(x.maneuver));
  if (!s) return null;
  return { icon: /left/.test(s.maneuver) ? 'left' : 'right', text: `${s.maneuver.charAt(0).toUpperCase()}${s.maneuver.slice(1)} on ${s.street === 'the path' ? 'the path' : s.street}`, inM: Math.max(0, s.at_m - meters) };
}

export default function Walk() {
  const walkId = new URLSearchParams(location.search).get('walk') ?? '';
  const creds = walkCreds(walkId);
  const { state, send, status, refused } = useWalk(walkId, 'walker');
  const data = state.plan?.data;
  const usual = creds?.choice === 'usual' && !state.switchedAt;
  const line: LngLat[] = useMemo(() => (data ? (usual ? data.shortest : data.route) : []), [data, usual]);
  const steps = data ? (usual ? data.routeSteps.shortest : data.routeSteps.hootroute) : [];
  const stats = data ? (usual ? data.stats.shortest : data.stats.hootroute) : null;
  const replaying = gpsMode() === 'replay';
  const replay = useRef<GpsReplay | null>(null);
  const started = useRef(false);
  const [gpsErr, setGpsErr] = useState<string | null>(null);
  const [muted, setMute] = useState(isMuted());
  const [report, setReport] = useState(false);
  const [sharing, setShare] = useState<boolean>(creds?.sharing ?? true);
  const [shareErr, setShareErr] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [tab, setTab] = useState<'journey' | 'activity'>('journey');
  const spoken = useRef(0);

  // accept the reviewed plan once it arrives, then start following positions
  useEffect(() => {
    if (!data || started.current) return;
    started.current = true;
    if (state.phase !== 'preview') return;        // reopened mid-journey: the room history already has the start
    send({ type: 'walk.accept', choice: usual ? 'usual' : 'hootroute' });
    send({ type: 'walk.start', replay: replaying });
  }, [data, state.phase, send, usual, replaying]);

  // GPS: the phone's real position, or a labelled replay along the route for indoor demos
  const lineKey = line.length ? `${line[0]}:${line[line.length - 1]}:${line.length}` : '';
  useEffect(() => {
    if (!lineKey || state.phase === 'arrived') return;
    if (replaying) {
      const ts = state.plan?.timeScale ?? 6; const t = state.plan?.thresholds;
      replay.current?.stop();
      replay.current = new GpsReplay(send, line, state.switchedAt ? null : data?.stopAt ?? null, ts, t ? (t.stopSeconds + t.replySeconds + t.escalateSeconds * 4) * 1000 / ts + 15000 : 60000);
      replay.current.start();
      return () => replay.current?.stop();
    }
    const cum = cumulative(line);
    return watchLocation((f) => {
      const pr = project(line, f.lngLat, cum);
      send({ type: 'walk.position', lngLat: f.lngLat, heading: f.heading, speed: f.speed, progress: pr.meters / cum[cum.length - 1], replay: false, accuracy: f.accuracy });
    }, setGpsErr);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lineKey, replaying]);
  useEffect(() => { if (state.lastReply?.reply === 'fine') replay.current?.resume(); }, [state.lastReply]);
  useEffect(() => { if (state.phase === 'arrived') replay.current?.stop(); }, [state.phase]);

  // speak what the agents say (the walker can mute)
  useEffect(() => {
    if (state.say && state.say.ts > spoken.current) { spoken.current = state.say.ts; if (!muted) void speak(state.say.text); }
  }, [state.say, muted]);
  useEffect(() => { if (state.sharing !== undefined) setShare(state.sharing); }, [state.sharing]);

  const pos = state.position?.lngLat ?? null;
  const meters = useMemo(() => (pos && line.length > 1 ? project(line, pos).meters : 0), [pos, line]);
  const total = useMemo(() => (line.length > 1 ? cumulative(line).at(-1) ?? 0 : 0), [line]);
  const remainMin = total ? Math.max(0, (total - meters) / 1.35 / 60) : stats?.minutes ?? 0;
  const turn = nextTurn(steps, meters);
  const rec = state.recovery && !state.recovery.chosen ? state.recovery : null;
  const link = sharing ? walkCreds(walkId)?.guardianUrl ?? null : null;
  const log = [...state.log].reverse().slice(0, 40);

  const flipShare = async (v: boolean) => {
    setShareErr(null);
    try { const r = await setSharing(walkId, v); setShare(r.active); } catch (e) { setShareErr(errorText(e, 'Could not change sharing.')); }
  };
  const sendLink = async () => {
    if (!link) return;
    try {
      if (navigator.share) await navigator.share({ title: 'Follow my journey', url: link });
      else { await navigator.clipboard.writeText(link); setCopied(true); setTimeout(() => setCopied(false), 2500); }
    } catch { /* closed the share sheet */ }
  };
  const routes = useMemo(() => {
    const r = line.length ? [{ id: 'active', coords: line, active: true }] : [];
    return rec ? [...r, ...rec.options.map((o) => ({ id: `rec-${o.id}`, coords: o.coords, active: false, dashed: true }))] : r;
  }, [line, rec]);
  const narrow = typeof window !== 'undefined' && window.innerWidth <= 760;

  if (!creds && refused) return <Gate text="This phone doesn't hold the walker key for this journey." />;
  if (!walkId) return <Gate text="No journey selected." />;

  return (
    <div className="app app--live">
      <MapCanvas routes={routes} start={line[0]} end={line.at(-1)} puck={pos} progressM={meters} fitKey={`${lineKey}:${rec?.recoveryId ?? ''}`} follow={!rec && state.phase !== 'arrived'}
        pad={narrow ? { left: 0, bottom: window.innerHeight * 0.5 } : { left: 420, bottom: 0 }} />

      {replaying && <span className="tape badge badge--amber">GPS replay · demo</span>}
      {state.phase !== 'arrived' && data && (
        <div className="banner fade" aria-live="polite">
          <span className="banner__icon"><Icon name={turn?.icon ?? 'straight'} size={22} /></span>
          <div style={{ minWidth: 0 }}>
            <div className="banner__main">{turn ? turn.text : `Continue to ${data.end.name}`}</div>
            <div className="mono small muted">{turn ? `in ${Math.max(10, Math.round(turn.inM / 10) * 10)} m` : `${Math.round(total - meters)} m left`}</div>
          </div>
        </div>
      )}

      <section className="panel" aria-label="Live journey">
        <header className="panel__head">
          <Brand sub={status === 'online' ? 'live' : status} />
          <button className="btn btn--quiet btn--sm" onClick={() => { setMuted(!muted); setMute(!muted); }} aria-pressed={muted}>{muted ? 'Voice off' : 'Voice on'}</button>
        </header>
        <div className="panel__body">
          {!data && <p className="p">Waiting for Scoot McRoute's plan…</p>}
          {data && state.phase !== 'arrived' && (
            <>
              <div className="stack--tight" style={{ marginTop: 6 }}>
                <span className="eyebrow">To {data.end.name}</span>
                <div className="kpis">
                  <div className="kpi"><span className="mono">{Math.round(remainMin)}</span><small>min left</small></div>
                  <div className="kpi"><span className="mono">{minuteClock(nowMin() + remainMin)}</span><small>arrive</small></div>
                  <div className="kpi"><span className="mono">{stats?.score ?? '—'}</span><small>route score</small></div>
                </div>
              </div>
              <div className="tabs" role="tablist">
                <button role="tab" className="tab" aria-selected={tab === 'journey'} onClick={() => setTab('journey')}>Journey</button>
                <button role="tab" className="tab" aria-selected={tab === 'activity'} onClick={() => setTab('activity')}>Agent activity · {state.log.length}</button>
              </div>
              {tab === 'journey' && (
                <>
                  {state.say && <div key={state.say.ts} className="card reveal stack--tight"><Agent id={state.say.agent} state={Date.now() - state.say.ts < 6000 ? 'talking' : 'idle'} /><p style={{ margin: 0 }}>{state.say.text}</p></div>}
                  <button className="btn btn--ghost btn--block" onClick={() => setReport(true)}><Icon name="flag" size={16} /> Report a problem ahead</button>
                  <div className="card stack--tight">
                    <div className="between"><span style={{ fontWeight: 600 }}>Share live location</span><Toggle on={sharing} onChange={(v) => void flipShare(v)} label="Share live location" /></div>
                    <span className="faint small">{sharing ? 'Only people with your link can see where you are. Stop any time; the link dies.' : 'Sharing is off. Nobody sees your position and no text or call goes out.'}</span>
                    {link && <button className="btn btn--quiet btn--sm" style={{ alignSelf: 'flex-start' }} onClick={() => void sendLink()}><Icon name="share" size={15} /> {copied ? 'Link copied' : 'Send link to your contact'}</button>}
                    {shareErr && <span className="error">{shareErr}</span>}
                  </div>
                  {gpsErr && !replaying && <p className="error">{gpsErr}</p>}
                </>
              )}
              {tab === 'activity' && (
                <div className="trace">
                  {log.length === 0 && <p className="p small">Agent messages appear here with the reason for each action.</p>}
                  {log.map((l) => (
                    <div key={l.id} className="step step--ok">
                      <span className="step__rail"><i /></span>
                      <span className="step__title">{PERSONA[l.agent as AgentName] ?? l.agent}{l.to ? <span> → {l.to}</span> : null}</span>
                      <span className="step__ms">{new Date(l.ts).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}</span>
                      <span className="step__sum" style={{ fontFamily: 'var(--font)', letterSpacing: 0 }}>{l.text}</span>
                      <span className="step__why">{l.reason}</span>
                    </div>
                  ))}
                </div>
              )}
            </>
          )}
          {state.phase === 'arrived' && (
            <div className="stack fade" style={{ marginTop: 8 }}>
              <h1 className="h1">You've arrived.</h1>
              {state.summary && <p className="p" style={{ color: 'var(--fg)' }}>{state.summary}</p>}
              {state.reportBy && <span className="faint tiny">Report by {state.reportBy}. Location sharing has stopped.</span>}
            </div>
          )}
        </div>
        <footer className="panel__foot">
          {state.phase === 'arrived'
            ? <Link className="btn btn--primary btn--block" to="/">Plan another journey</Link>
            : <button className="btn btn--quiet btn--block" onClick={() => { replay.current?.stop(); send({ type: 'walk.end', outcome: 'ended', summary: 'Walk ended by the walker.' }); }}>End journey and stop sharing</button>}
        </footer>
      </section>

      {state.phase === 'checkin' && state.checkin && <CheckIn text={state.checkin.text} reason={state.checkin.reason} deadline={state.checkin.deadline} sharing={sharing} onReply={(r) => send({ type: 'checkin.reply', reply: r, via: 'tap' })} />}
      {state.phase === 'escalated' && (
        <div className="overlay" role="alertdialog" aria-label="Help">
          <div className="dialog">
            <span className="badge badge--red" style={{ alignSelf: 'flex-start' }}>No answer to the check-in</span>
            <h2 className="h2">{sharing ? 'Your contact can see your live location.' : 'Sharing is off, so nobody was alerted.'}</h2>
            {state.ladder && <p className="p small">{state.ladder.label}: {state.ladder.status}</p>}
            <button className="btn btn--primary" onClick={() => send({ type: 'checkin.reply', reply: 'fine', via: 'tap' })}><Icon name="check" size={16} /> I'm fine</button>
            <a className="btn btn--danger" href="tel:911">Call 911 yourself</a>
            <span className="faint tiny">HootRoute never calls 911 for you.</span>
          </div>
        </div>
      )}
      {rec && (
        <div className="overlay" role="dialog" aria-modal="true" aria-label="Mission Recovery">
          <div className="dialog" style={{ width: 'min(520px, 100%)' }}>
            <span className="eyebrow">Mission recovery</span>
            <h2 className="h2">{rec.reason}</h2>
            <div className="card stack--tight"><Agent id="head" /><p style={{ margin: 0 }}>{rec.explanation}</p><span className="faint tiny">explained by {rec.explainedBy}</span></div>
            <div className="stack">
              {[rec.current, ...rec.options].map((o) => (
                <div key={o.id} className="route" style={{ cursor: 'default' }}>
                  <span className="route__name">{o.label}{o.avoidsReport ? <span className="badge badge--mint">avoids report</span> : <span className="badge badge--amber">passes report</span>}</span>
                  <span className="route__min">{Math.round(o.stats.minutes)}<span className="faint" style={{ fontSize: 12 }}> min</span></span>
                  <span className="route__meta"><span>Score <b>{o.stats.score}</b></span><span>Longest empty <b>{o.stats.longestEmptyM} m</b></span>{o.liveEvidence ? <span>Live-checked places <b>{o.liveEvidence}</b></span> : null}</span>
                  <span style={{ gridColumn: '1 / -1' }}>
                    <button className={`btn btn--sm ${o.id === 'keep' ? 'btn--quiet' : 'btn--ghost'}`} onClick={() => send({ type: 'recovery.choose', recoveryId: rec.recoveryId, optionId: o.id })}>
                      {o.id === 'keep' ? 'Keep my route' : 'Switch to this route'}
                    </button>
                  </span>
                </div>
              ))}
            </div>
            <span className="faint tiny">Your route stays the same until you choose. Reports are yours, not verified, and nothing is sent to the city.</span>
          </div>
        </div>
      )}
      {report && <ReportDialog onClose={() => setReport(false)} onSend={(kind, note) => { send({ type: 'obstacle.report', kind, ...(note ? { note } : {}) }); setReport(false); }} />}
    </div>
  );
}

function CheckIn({ text, reason, deadline, sharing, onReply }: { text: string; reason: string; deadline: number; sharing: boolean; onReply: (r: 'fine' | 'help') => void }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => { const t = setInterval(() => setNow(Date.now()), 500); return () => clearInterval(t); }, []);
  const secs = Math.max(0, Math.round((deadline - now) / 1000));
  return (
    <div className="overlay" role="alertdialog" aria-label="Check-in">
      <div className="dialog">
        <Agent id="checker" />
        <h2 className="h1">{text}</h2>
        <p className="p small">{reason}</p>
        <button className="btn btn--primary" onClick={() => onReply('fine')}><Icon name="check" size={16} /> I'm fine</button>
        <button className="btn btn--ghost" onClick={() => onReply('help')}>I need help</button>
        <span className="faint tiny mono">{secs} s · {sharing ? 'then your contact is alerted on the live link' : 'sharing is off, so nobody is alerted'}</span>
      </div>
    </div>
  );
}

function ReportDialog({ onClose, onSend }: { onClose: () => void; onSend: (k: ObstacleKind, note: string) => void }) {
  const [kind, setKind] = useState<ObstacleKind | null>(null);
  const [note, setNote] = useState('');
  return (
    <div className="overlay" role="dialog" aria-modal="true" aria-label="Report a problem">
      <div className="dialog">
        <Agent id="rescuer" />
        <h2 className="h2">What's ahead?</h2>
        <div className="chips">{KINDS.map(([k, l]) => <button key={k} className="chip" aria-pressed={kind === k} onClick={() => setKind(k)}>{l}</button>)}</div>
        <label className="field"><span className="sr">Note</span><input value={note} maxLength={140} onChange={(e) => setNote(e.target.value)} placeholder="Optional note, e.g. sidewalk fenced off" /></label>
        <p className="faint tiny" style={{ margin: 0 }}>Wally asks Professor Hoot for routes around it. Nothing changes until you choose.</p>
        <div className="row"><button className="btn btn--primary" disabled={!kind} onClick={() => kind && onSend(kind, note.trim())}>Find another way</button><button className="btn btn--quiet" onClick={onClose}>Cancel</button></div>
      </div>
    </div>
  );
}

function Gate({ text }: { text: string }) {
  return <div className="app" style={{ display: 'grid', placeItems: 'center', padding: 24 }}><div className="dialog"><Brand /><p className="p">{text}</p><Link className="btn btn--primary" to="/">Plan a journey</Link></div></div>;
}
