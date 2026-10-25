import { Logo } from '../components/Logo';
import { BRAND } from '../lib/brand';
import { useEffect, useMemo, useRef, useState } from 'react';
import QRCode from 'qrcode';
import MapView from '../components/MapView';
import { AgentRow, DemoTape, Icon, LinkBadge, Mascot } from '../components/ui';
import { DemoEngine } from '../lib/engine';
import { timeOf } from '../lib/format';
import { getRoomStore, isGatewayMode, loadSettings, mergedPlaces, useWalk, useWalkData, walkIdFromUrl, type LogEntry } from '../lib/store';
import { createWalk, gpsMode, listWalks, walkCreds } from '../lib/api';
import { GpsReplay } from '../lib/replay';
import type { DemoData } from '../lib/types';
import type { MascotState } from '../lib/types';
import './room.css';

// The laptop on stage: map with scores, agent trace, replay timeline, city ranking.

interface BlockVision {
  status: 'available' | 'missing_key' | 'no_recent_image' | 'unavailable' | 'analysis_unavailable';
  message: string;
  imageUrl?: string;
  capturedAt?: string;
  sourceUrl?: string;
}

export default function Room() {
  const [walkId, setWalkId] = useState(() => new URLSearchParams(location.search).get('walk') || (isGatewayMode() ? '' : walkIdFromUrl()));
  const settings = useMemo(loadSettings, []);
  const { state, send, status, room } = useWalk(walkId || 'none', 'room');
  const { data, error } = useWalkData(state);
  const [starting, setStarting] = useState<string | null>(null);
  const liveReplay = useRef<GpsReplay | null>(null);

  // live: follow the walk in the URL, else the newest active walk
  useEffect(() => {
    if (!isGatewayMode() || walkId) return;
    listWalks(true).then((ws) => { if (ws[0]) follow(ws[0].id); }, () => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const follow = (id: string) => {
    const q = new URLSearchParams(location.search); q.set('walk', id);
    history.replaceState(null, '', `${location.pathname}?${q}`);
    setWalkId(id);
  };
  const [qr, setQr] = useState('');
  const [stretch, setStretch] = useState<string | null>(null);
  const [vision, setVision] = useState<BlockVision | null>(null);
  const [draft, setDraft] = useState(false);
  const [now, setNow] = useState(Date.now());
  const engine = useRef<DemoEngine | null>(null);
  const replayTimer = useRef<number | null>(null);
  const feedEnd = useRef<HTMLDivElement>(null);
  const guardianParams = new URLSearchParams();
  if (!isGatewayMode()) {
    guardianParams.set('agents', 'demo');
    if (settings.destination) {
      guardianParams.set('destination', `${settings.destination.lngLat[1]},${settings.destination.lngLat[0]}`);
      guardianParams.set('destinationName', settings.destination.name);
    }
  }
  const guardianUrl = walkCreds(walkId)?.guardianUrl ?? `${location.origin}/guardian/${walkId}${guardianParams.size ? `?${guardianParams}` : ''}`;

  useEffect(() => {
    QRCode.toDataURL(guardianUrl, { margin: 1, width: 360, color: { dark: '#10141C', light: '#ECE7DC' } }).then(setQr).catch(() => setQr(''));
  }, [guardianUrl]);
  useEffect(() => {
    const t = window.setInterval(() => setNow(Date.now()), 1000);
    return () => {
      window.clearInterval(t);
      if (replayTimer.current !== null) window.clearInterval(replayTimer.current);
      engine.current?.dispose();
      liveReplay.current?.stop();
    };
  }, []);
  useEffect(() => {
    feedEnd.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [state.log.length]);
  // open the "why this street" card on the walker's stretch when a check-in starts
  useEffect(() => {
    if (state.phase === 'checkin' || state.phase === 'escalated') setStretch(data?.dimStretches.find((d) => d.onRoute)?.id ?? null);
  }, [state.phase, data]);
  useEffect(() => {
    const selected = data?.dimStretches.find((d) => d.id === stretch);
    setVision(null);
    if (!selected) return;
    const controller = new AbortController();
    const mid = selected.line[Math.floor(selected.line.length / 2)];
    fetch(`/api/block-vision?lat=${mid[1]}&lon=${mid[0]}`, { signal: controller.signal })
      .then((response) => response.ok ? response.json() as Promise<BlockVision> : Promise.reject())
      .then(setVision)
      .catch(() => { if (!controller.signal.aborted) setVision({ status: 'unavailable', message: 'Street-level imagery is unavailable right now.' }); });
    return () => controller.abort();
  }, [data, stretch]);

  // live: a real walk on the stage corridor, positions replayed (badged) so it runs indoors; the agents are the real ones
  async function startLiveDemo() {
    setStarting('Asking the Guide for the stage route…');
    try {
      const corridor = (await fetch('/data/demo-route.json').then((r) => r.json())) as DemoData;
      const w = await createWalk({
        from: corridor.start, to: corridor.end, when: { day: corridor.scenario.day ?? 4, minute: corridor.scenario.departureMinute }, choice: 'hootroute',
        walker: settings.walkerName, guardian: settings.guardianName, guardianPhone: settings.guardianPhone, thresholds: settings.thresholds, replay: true, timeScale: settings.timeScale,
      });
      follow(w.walkId);
      const walker = getRoomStore(w.walkId, 'walker');
      const t0 = Date.now();
      while (!walker.state.plan?.data && Date.now() - t0 < 30000) await new Promise((r) => setTimeout(r, 200));
      const planned = walker.state.plan?.data;
      if (!planned) throw new Error('The Guide did not answer in time.');
      walker.room.send({ type: 'walk.accept', choice: 'hootroute' });
      walker.room.send({ type: 'walk.start', replay: true });
      const t = walker.state.plan!.thresholds;
      liveReplay.current?.stop();
      liveReplay.current = new GpsReplay((m) => walker.room.send(m), planned.route, planned.stopAt, settings.timeScale, (t.stopSeconds + t.replySeconds + t.escalateSeconds * 4) * 1000 + 15000, 300);
      const unsub = walker.room.subscribe((e) => {
        if (e.msg.type === 'checkin.reply' && e.msg.reply === 'fine') liveReplay.current?.resume();
        if (e.msg.type === 'walk.end') { liveReplay.current?.stop(); unsub(); }
      });
      liveReplay.current.start();
      setStarting(null);
    } catch (e) {
      setStarting(e instanceof Error ? e.message : 'Could not start the demo walk.');
    }
  }

  if (!data) {
    return (
      <div className="screen" data-theme="night" role={error ? 'alert' : undefined} style={{ padding: 24, display: 'flex', flexDirection: 'column', gap: 16, maxWidth: 520 }}>
        <Logo size={24} />
        <p className="t-spoken">{error ?? starting ?? (walkId ? 'Waiting for the Guide\'s plan…' : 'No active walk yet. Start one on a phone from /plan, or run the stage walk here.')}</p>
        {isGatewayMode() && !walkId && <button type="button" className="room__action" onClick={() => void startLiveDemo()}><Icon name="play" size={16} /> Start demo walk here</button>}
      </div>
    );
  }

  const walkRunning = state.phase === 'walking' || state.phase === 'checkin' || state.phase === 'escalated';
  // The room only runs the demo itself if no walker phone has planned/started a walk.
  const ensureEngine = () => {
    if (!engine.current) engine.current = new DemoEngine(room, data, settings);
    return engine.current;
  };
  const startDemo = () => {
    if (isGatewayMode()) { void startLiveDemo(); return; }
    const e = ensureEngine();
    const fresh = state.phase !== 'preview' || !state.plan;
    if (state.phase !== 'preview') send({ type: 'walk.reset' });
    if (fresh) e.plan();
    window.setTimeout(() => e.start('hootroute'), fresh ? 700 : 0);
  };
  const runAudit = () => {
    if (isGatewayMode()) { send({ type: 'audit.run' }); return; }
    send({ type: 'audit.run' });
  };

  const places = mergedPlaces(data, state);
  const sel = data.dimStretches.find((d) => d.id === stretch);
  const ranking = state.audit?.ranking ?? data.darknessDebt;
  const maxMin = Math.max(...ranking.map((r) => r.minutes));
  const puck = state.position && state.phase !== 'preview'
    ? { lngLat: state.position.lngLat, heading: state.position.heading, variant: (state.phase === 'escalated' ? 'alert' : state.phase === 'checkin' ? 'checkin' : 'normal') as 'alert' | 'checkin' | 'normal' }
    : null;

  return (
    <div className="screen room" data-theme="night">
      {/* ---------- sidebar ---------- */}
      <aside className="room__side">
        <div>
          <Logo size={24} />
          <div className="t-mono">control room</div>
        </div>
        <nav className="room__nav">
          <span className="room__nav-item room__nav-item--on">Live walk {state.alert && !state.alert.ackBy && <b className="room__badge">1 alert</b>}</span>
          <span className="room__nav-item">Agents</span>
          <span className="room__nav-item">City ranking</span>
          <span className="room__nav-item">Overnight audit</span>
        </nav>
        <div className="room__qr card">
          {qr ? <img src={qr} alt={`QR code for ${guardianUrl}`} /> : <div style={{ height: 160 }} />}
          <div>
            <div className="t-headline" style={{ fontSize: 14 }}>Scan to be the guardian</div>
            <div className="t-mono" style={{ wordBreak: 'break-all' }}>{guardianUrl.replace(/^https?:\/\//, '')}</div>
          </div>
        </div>
        <div style={{ flex: 1 }} />
        <button type="button" className="room__action" onClick={startDemo} disabled={!!starting}>
          <Icon name="play" size={16} /> {starting ?? (walkRunning ? 'Start a new stage walk' : 'Start demo walk here')}
        </button>
        <button type="button" className="room__action" onClick={runAudit}>
          <Icon name="moon" size={16} /> Run overnight audit
        </button>
        <div className="room__det card">
          <div>
            <div className="t-headline" style={{ fontSize: 13 }}>{isGatewayMode() ? 'Live agents' : 'Deterministic mode'}</div>
          <div className="t-caption" style={{ fontSize: 11 }}>conditions, not a safety rating · cached route and offline map</div>
          </div>
          <LinkBadge status={status} />
        </div>
          <DemoTape label={isGatewayMode() ? (walkRunning ? state.replay ? `DEMO · GPS REPLAY · ×${state.plan?.timeScale ?? settings.timeScale} · LIVE AGENTS` : 'LIVE · WALKER GPS' : `LIVE AGENTS · GPS ${gpsMode() === 'replay' ? 'REPLAY' : 'REAL'}`) : 'DEMO · GPS REPLAY'} />
        <div className="t-mono" style={{ fontSize: 10 }}>OSM · SF 311 · missing hours count closed</div>
      </aside>

      {/* ---------- map ---------- */}
      <main className="room__map">
        <MapView
          theme="night"
          data={data}
          choice={state.choice}
          places={places}
          showSegments
          brightened={Object.keys(state.brightened)}
          puck={puck}
          progress={state.position?.progress ?? 0}
          camera="fit"
          padding={{ top: 120, bottom: 110, left: 60, right: 380 }}
          onStretchClick={(id) => setStretch(id)}
        />
        <header className="room__header">
          <div>
            <h1 className="t-title" style={{ fontSize: 20 }}>{data.scenario.label} scenario</h1>
            <div className="t-caption" style={{ fontSize: 12 }}>{data.scenario.area} · {data.scenario.segmentsScored.toLocaleString()} street segments scored</div>
          </div>
          <div className="room__pills">
            <span className="chip t-mono"><span className="dot" /> OSM + SF 311</span>
            <span className="chip t-mono"><span className="dot" /> {data.places.length} listed places</span>
            <span className="chip t-mono"><span className="dot" style={{ background: 'var(--route)' }} /> 4 agents · Head, Guide, Checker, Rescuer</span>
          </div>
        </header>

        <div className="room__cards">
          {sel ? (
            <section className="card why" aria-label="Why this street">
              <div className="why__head">
                <div>
                  <div className="t-number muted" style={{ fontSize: 12, letterSpacing: 1.2 }}>WHY THIS STREET</div>
                  <div className="t-headline">{sel.name}</div>
                </div>
                <div style={{ textAlign: 'right' }}>
                  <div className="t-number" style={{ fontSize: 28, lineHeight: '28px' }}>{sel.score}</div>
                  <Confidence level={sel.confidence} />
                </div>
              </div>
              <div className="why__sect"><span>Lamp evidence</span><p>{sel.lampEvidence}</p><em className="t-mono">{sel.lampSource}</em></div>
              <div className="why__sect"><span>Listed places at arrival</span><p>{sel.openPlaces}</p><em className="t-mono">{sel.openSource}</em></div>
              <div className="why__sect">
                <span>Look at the block · explanation only</span>
                <p>{vision?.message ?? 'Checking recent street imagery…'}</p>
                {vision?.imageUrl && vision.sourceUrl && <a href={vision.sourceUrl} target="_blank" rel="noopener noreferrer"><img src={vision.imageUrl} alt={`Mapillary street view captured ${vision.capturedAt ?? 'on an unknown date'}`} style={{ display: 'block', width: '100%', maxHeight: 150, objectFit: 'cover', borderRadius: 8 }} /></a>}
                {vision?.capturedAt && <em className="t-mono">Mapillary · captured {vision.capturedAt} · never used in the score</em>}
              </div>
              <div className="why__say"><Mascot agent="head" state="talking" size={28} /><p>{sel.why}</p></div>
              <button type="button" className="why__close" onClick={() => setStretch(null)} aria-label="Close">×</button>
            </section>
          ) : (
            <section className="card why why--hint">
              <Icon name="moon" size={16} /> Tap a dashed stretch to see why it scores low.
            </section>
          )}
          <section className="card debt" aria-label="Darkness debt">
            <div className="debt__head">
              <Mascot agent="head" state={state.audit ? 'done' : 'idle'} size={34} />
              <div>
                <div className="t-headline" style={{ fontSize: 14 }}>Darkness debt · modeled trips</div>
                <div className="t-caption" style={{ fontSize: 11 }}>modeled walker-minutes on lower-light streets</div>
              </div>
            </div>
            {ranking.map((r) => (
              <div key={r.street} className="debt__row">
                <div><span>{r.street}</span><span className="t-mono">{r.minutes} min</span></div>
                <i><b style={{ width: `${(r.minutes / maxMin) * 100}%` }} /></i>
              </div>
            ))}
            <button type="button" className="debt__btn" onClick={() => setDraft(true)}>Draft 311 report (not sent)</button>
          </section>
        </div>
        <div className="room__legend card">
          <div>Brighter + wider = more light &amp; open places</div>
          <div className="muted">Dashed = low confidence · never a crime heatmap</div>
        </div>

        <Timeline state={state} now={now} departureMinute={data.scenario.departureMinute} />
      </main>

      {/* ---------- feed ---------- */}
      <aside className="room__feed">
        <header className="room__feed-head">
          <h2 className="t-title" style={{ fontSize: 20 }}>Agent feed</h2>
          <span className="dot dot--live" />
          <span className="t-mono" style={{ marginLeft: 'auto' }}>{isGatewayMode() ? (walkRunning && !state.replay ? 'Gateway · live walk' : 'Gateway · demo replay') : 'Local demo replay'}</span>
        </header>
        <div className="room__feed-list">
          {state.log.length === 0 && (
            <div className="room__empty">
              <Mascot agent="checker" state="idle" size={72} />
              <p className="t-caption">Waiting for the night shift. Open <b>/walk</b> on the walker phone, or press <b>Start demo walk here</b>.</p>
            </div>
          )}
          {state.log.map((e, i) => (
            <AgentRow key={e.id} agent={e.agent} state={moodOf(e, i === state.log.length - 1)} to={e.to} ts={e.ts} text={e.text} reason={e.reason} />
          ))}
          <div ref={feedEnd} />
        </div>
      </aside>

      {draft && (
        <div className="g-modal" onClick={() => setDraft(false)} role="dialog" aria-label="Draft 311 report">
          <div className="g-modal__card" onClick={(e) => e.stopPropagation()} style={{ borderRadius: 24, marginBottom: 40 }}>
            <h2 className="t-title">Draft 311 report</h2>
            <p style={{ margin: 0 }}>{state.audit?.draft311 ?? `DRAFT — not submitted. Review streetlight conditions on ${ranking[0].street}. The model estimates ${ranking[0].minutes} walker-minutes on lower-light segments in simulated trips. Confirm conditions before filing.`}</p>
            <p className="t-caption" style={{ margin: 0 }}>Reports stay drafts for human review. {BRAND} never files with the city on its own.</p>
            <button type="button" className="btn btn--secondary" onClick={() => setDraft(false)}>Close</button>
          </div>
        </div>
      )}
    </div>
  );
}

function moodOf(e: LogEntry, latest: boolean): MascotState {
  if (e.text.trim().endsWith('?')) return 'thinking';
  if (/^(Re-scored|Ranked|Evidence filed|Check-in cleared)/.test(e.text)) return 'done';
  return latest ? 'talking' : 'idle';
}

function Confidence({ level }: { level: 'low' | 'medium' | 'high' }) {
  const n = level === 'high' ? 3 : level === 'medium' ? 2 : 1;
  return (
    <span className="conf" aria-label={`${level} confidence`}>
      {[0, 1, 2].map((i) => <i key={i} className={i < n ? 'on' : ''} />)} {level} conf.
    </span>
  );
}

function Timeline({ state, now, departureMinute }: { state: ReturnType<typeof useWalk>['state']; now: number; departureMinute: number }) {
  const start = state.startedAt;
  const end = state.phase === 'arrived' ? state.events[state.events.length - 1]?.ts ?? now : now;
  const span = start ? Math.max(1, end - start) : 1;
  const pos = (ts: number) => (start ? Math.min(1, Math.max(0, (ts - start) / span)) : 0);
  const elapsed = (ts: number) => {
    const seconds = start ? Math.max(0, Math.round((ts - start) / 1000)) : 0;
    return `+${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`;
  };
  const scenarioTime = `${String(Math.floor(departureMinute / 60) % 24).padStart(2, '0')}:${String(departureMinute % 60).padStart(2, '0')}`;
  const colorOf = (k: string) => (k === 'alert' ? 'var(--alert)' : k === 'checkin' ? 'var(--checkin)' : k === 'place' || k === 'fine' || k === 'ack' ? 'var(--open)' : 'var(--route)');
  return (
    <footer className="timeline">
      <div className="timeline__play"><Icon name={state.phase === 'walking' ? 'pause' : 'play'} size={16} /></div>
      <div className="timeline__label">
        <div className="t-number" style={{ fontSize: 15, letterSpacing: 1 }}>{start ? state.replay ? `REPLAY · ${elapsed(now)}` : `LIVE · ${timeOf(now, true)}` : `SCENARIO · ${scenarioTime}`}</div>
        <div className="t-caption" style={{ fontSize: 11 }}>{start ? state.replay ? 'Demo walk · GPS replay with an injected stop' : 'Live GPS from the walker phone' : 'Scenario route plan'}</div>
      </div>
      <div className="timeline__track">
        <div className="timeline__base" />
        <div className="timeline__done" style={{ transform: `scaleX(${start ? 1 : 0})` }} />
        {state.events.map((ev, i) => {
          const x = pos(ev.ts) * 100;
          const up = i % 2 === 1;
          return (
            <div key={`${ev.ts}-${i}`} className="timeline__stop" style={{ left: `${x}%` }}>
              <span className="timeline__dot" style={{ background: colorOf(ev.kind) }} />
              <span className={`timeline__txt${up ? ' timeline__txt--up' : ''}`}><b>{ev.label}</b><em className="t-mono">{state.replay ? elapsed(ev.ts) : timeOf(ev.ts, true).slice(0, 5)}</em></span>
            </div>
          );
        })}
      </div>
      <div className="timeline__foot t-caption">Agent messages, voice turns and guardian events are logged with a reason (agent_log).</div>
    </footer>
  );
}
