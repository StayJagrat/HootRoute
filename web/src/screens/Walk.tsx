import { useEffect, useMemo, useRef, useState } from 'react';
import { Call911, RescueLadder, Steps } from '../components/AgentPanels';
import { BRAND } from '../lib/brand';
import { Link, useNavigate } from 'react-router-dom';
import MapView from '../components/MapView';
import { Button, DemoTape, HoldButton, Icon, Initials, LinkBadge, Mascot, Sheet, StreetSign } from '../components/ui';
import { DemoEngine } from '../lib/engine';
import { cumulative, lineLength, project, turnsFromSteps } from '../lib/geo';
import { AGENT_LABEL, meters, timeOf } from '../lib/format';
import { getRoomStore, loadSettings, mergedPlaces, useWalk, useWalkData, walkIdFromUrl } from '../lib/store';
import { gpsMode, isLive, walkCreds } from '../lib/api';
import { loadPrefs } from '../lib/prefs';
import { PERSONA, SHORT } from '../lib/personas';
import { RecoverySheet, ReportSheet, SharingControl } from '../components/LiveJourney';
import '../components/hoot.css';
import { GpsReplay } from '../lib/replay';
import { canListen, isMuted, listen, setMuted, speak, unlockAudio, type ListenerHandle } from '../lib/voice';
import { keepAwake, vibrate, watchLocation } from '../lib/device';
import './walk.css';

const engineEnabled = () => !isLive();

export default function Walk() {
  const walkId = walkIdFromUrl();
  const settings = useMemo(loadSettings, []);
  const { state, send, status, room } = useWalk(walkId || 'none', 'walker');
  const { data, error, waiting } = useWalkData(state);
  const engine = useRef<DemoEngine | null>(null);
  const replay = useRef<GpsReplay | null>(null);
  const listener = useRef<ListenerHandle | null>(null);
  const [muted, setMutedState] = useState(isMuted());
  const [now, setNow] = useState(Date.now());
  const [gpsError, setGpsError] = useState<string | null>(null);
  const nav = useNavigate();
  const guardianName = state.plan?.guardian ?? settings.guardianName;
  const guardianFirst = guardianName.split(' ')[0];
  const timeScale = state.plan?.timeScale ?? settings.timeScale;
  const ownsWalk = !isLive() || !!walkCreds(walkId);
  const lowDistraction = useMemo(() => loadPrefs().lowDistraction, []);
  const [reportOpen, setReportOpen] = useState(false);
  const recoveryId = state.recovery?.recoveryId;
  useEffect(() => { if (recoveryId) setReportOpen(false); }, [recoveryId]);   // options arrived: the recovery card takes over
  const [dismissed, setDismissed] = useState<string | null>(null);
  const [shareLocal, setShareLocal] = useState<{ v: boolean; ts: number } | null>(null);
  const live = isLive();

  // demo engine: plays the agents from cached data unless ?engine=off (gateway drives)
  useEffect(() => {
    if (!data || !engineEnabled()) return;
    const e = new DemoEngine(room, data, settings);
    engine.current = e;
    // In demo mode the walker phone owns the walk: every load starts a fresh one.
    // Wait for the room link to settle first so relay history can't overwrite the reset.
    // (Also keeps React StrictMode's mount/unmount/mount from planning twice.)
    let cancelled = false;
    const store = getRoomStore(walkId, 'walker');
    (async () => {
      const t0 = Date.now();
      while (store.status === 'connecting' && Date.now() - t0 < 3000) await new Promise((r) => setTimeout(r, 100));
      await new Promise((r) => setTimeout(r, 250));
      if (cancelled) return;
      room.send({ type: 'walk.reset' });
      e.plan();
    })();
    return () => {
      cancelled = true;
      e.dispose();
      engine.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data]);

  // speak every new line (low-distraction: only the Guide's turn prompts, check-ins and the Rescuer)
  const lastSaid = useRef(0);
  useEffect(() => {
    if (state.say && state.say.ts > lastSaid.current && state.phase !== 'preview') {
      lastSaid.current = state.say.ts;
      const quietable = state.phase === 'walking' && (state.say.agent === 'checker' || state.say.agent === 'head');
      if (!(lowDistraction && quietable)) void speak(state.say.text);
    }
  }, [state.say, state.phase, lowDistraction]);

  // buzz on check-in
  useEffect(() => {
    if (state.phase === 'checkin') vibrate([80, 60, 80]);
  }, [state.phase]);

  // tick for countdowns and "x s ago"
  useEffect(() => {
    const t = window.setInterval(() => setNow(Date.now()), 250);
    return () => window.clearInterval(t);
  }, []);

  // live mode, real GPS: every fix goes to the gateway; the Checker computes progress, stops and detours from it
  const activeWalk = state.phase !== 'preview' && state.phase !== 'arrived';
  useEffect(() => {
    if (engineEnabled() || gpsMode() !== 'real' || state.plan?.replay || !data || !activeWalk || !ownsWalk) return;
    const line = state.choice === 'usual' ? data.shortest : data.route;
    const cum = cumulative(line);
    const total = lineLength(line);
    return watchLocation(
      (f) => {
        setGpsError(null);
        const pr = project(line, f.lngLat, cum);
        send({ type: 'walk.position', lngLat: f.lngLat, heading: f.heading, speed: f.speed, progress: pr.meters / total, replay: false, accuracy: f.accuracy });
      },
      (msg) => setGpsError(msg),
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data?.route, activeWalk, state.choice, send, ownsWalk, state.plan?.replay]);

  // live mode, GPS replay: walk on once the walker answers a check-in; stop at the end of the walk
  useEffect(() => {
    if (state.lastReply?.reply === 'fine') replay.current?.resume();
  }, [state.lastReply]);
  useEffect(() => {
    if (state.phase === 'arrived') replay.current?.stop();
  }, [state.phase]);
  useEffect(() => () => replay.current?.stop(), []);

  // stop listening/awake when the walk ends
  useEffect(() => {
    if (state.phase === 'arrived') {
      listener.current?.stop();
      listener.current = null;
      void keepAwake(false);
    }
  }, [state.phase]);
  useEffect(() => () => {
    listener.current?.stop();
    void keepAwake(false);
  }, []);

  const go = (choice: 'hootroute' | 'usual') => {
    // walk.accept only knows hootroute | usual; a 'balanced' walk is already the plan's main route on the gateway
    if (!data) return;
    unlockAudio(); // the "Walk with me" tap doubles as the audio unlock
    void keepAwake(true);
    if (canListen() && !listener.current) {
      listener.current = listen((intent) => send({ type: 'checkin.reply', reply: intent, via: 'voice' }));
    }
    if (engine.current) engine.current.start(choice);
    else {
      const replaying = gpsMode() === 'replay' || !!state.plan?.replay;
      send({ type: 'walk.accept', choice });
      send({ type: 'walk.start', replay: replaying });
      if (replaying) {
        const t = state.plan?.thresholds ?? settings.thresholds;
        replay.current?.stop();
        replay.current = new GpsReplay(send, choice === 'usual' ? data.shortest : data.route, data.stopAt, timeScale, (t.stopSeconds + t.replySeconds + t.escalateSeconds * 4) * 1000 + 15000, 300);
        replay.current.start();
      }
    }
  };

  const endWalk = () => {
    replay.current?.stop();
    send({ type: 'walk.end', outcome: 'ended', summary: 'Walk ended by the walker.' });
  };

  const reply = (r: 'fine' | 'help') => send({ type: 'checkin.reply', reply: r, via: 'tap' });

  const toggleMute = () => {
    setMuted(!muted);
    setMutedState(!muted);
  };

  const line = data ? (state.choice === 'usual' ? data.shortest : data.route) : [];
  const total = useMemo(() => (line.length ? lineLength(line) : 0), [line]);
  const turnList = useMemo(() => (line.length && data ? turnsFromSteps(data.routeSteps[state.choice === 'usual' ? 'shortest' : 'hootroute'], lineLength(line)) : []), [line, data, state.choice]);

  if (isLive() && (!walkId || !ownsWalk)) {
    return (
      <div className="screen" data-theme="night" style={{ padding: 24, display: 'flex', flexDirection: 'column', gap: 16 }}>
        <p className="t-spoken">{walkId ? 'This walk was started on another phone. Open the guardian link to follow it.' : `Plan a walk first and ${SHORT.guide} will pick the route.`}</p>
        <Link className="btn btn--primary btn--block" to={walkId ? `/guardian/${walkId}` : '/plan'} style={{ textDecoration: 'none' }}>{walkId ? 'Open guardian view' : 'Plan a walk'}</Link>
      </div>
    );
  }
  if (!data) return <div className="screen" data-theme="night" role={error ? 'alert' : undefined} style={{ padding: 24 }}>{error ?? (waiting ? `${SHORT.guide} is planning your route…` : 'Loading route…')}</div>;

  const places = mergedPlaces(data, state);
  const progress = state.position?.progress ?? 0;
  const walked = progress * total;
  const next = turnList.find((t) => t.meters > walked + 3) ?? turnList[turnList.length - 1];
  const toNext = next ? next.meters - walked : 0;
  const remaining = Math.max(0, total - walked);
  const etaMin = remaining / 1.35 / 60;
  const phase = state.phase;
  const plan = state.plan;
  const stats = plan?.stats ?? data.stats;
  const demoClock = new Date(now);
  demoClock.setHours(Math.floor(data.scenario.departureMinute / 60), data.scenario.departureMinute % 60, 0, 0);
  const arrive = state.replay && engineEnabled()
    ? demoClock.getTime() + (state.choice === 'usual' ? stats.shortest.minutes : stats.hootroute.minutes) * 60000
    : now + etaMin * 60000;
  const brightened = Object.keys(state.brightened);
  const credsShare = walkCreds(walkId)?.sharing;
  // whichever is newer: this phone's own toggle, or the room's share.update
  const sharing = shareLocal && shareLocal.ts >= (state.sharingTs ?? 0) ? shareLocal.v : state.sharing ?? credsShare ?? true;
  const recovery = state.recovery && state.recovery.recoveryId !== dismissed && (phase === 'walking' || phase === 'preview') ? state.recovery : null;
  const justSwitched = state.switchedAt && now - state.switchedAt < 8000;
  const demoLabel = live ? '' : 'SIMULATED DEMO · ';

  const puck = state.position && phase !== 'preview'
    ? { lngLat: state.position.lngLat, heading: state.position.heading, variant: (phase === 'escalated' ? 'alert' : phase === 'checkin' ? 'checkin' : 'normal') as 'alert' | 'checkin' | 'normal' }
    : null;

  return (
    <div className="screen walk" data-theme="night">
      <MapView
        theme="night"
        data={data}
        choice={state.choice}
        places={places}
        showShortest={phase === 'preview'}
        showDimLabel={phase === 'preview'}
        brightened={brightened}
        puck={puck}
        progress={phase === 'preview' ? 0 : progress}
        camera={phase === 'preview' || phase === 'arrived' ? 'overview' : 'follow'}
        padding={phase === 'preview' ? { top: 90, bottom: 430, left: 30, right: 30 } : phase === 'checkin' ? { top: 140, bottom: 470 } : { top: 170, bottom: 380 }}
        bouncePlace={brightened[brightened.length - 1] ?? null}
      />
      {phase === 'checkin' && <div className="walk__scrim" />}

      {/* ---------- top ---------- */}
      <div className="walk__top">
        {phase === 'preview' ? (
          <div className="chip">
            <span className="dot" />
            {data.scenario.label} · leaving {data.start.name}
          </div>
        ) : phase !== 'arrived' && next ? (
          <StreetSign
            street={next.direction === 'arrive' ? data.end.name : next.street}
            direction={next.direction === 'arrive' ? 'arrive' : toNext > 160 ? 'straight' : next.direction}
            instruction={next.direction === 'arrive' ? `Arrive · ${meters(toNext)}` : `${toNext > 160 ? 'Then turn' : 'Turn'} ${next.direction} · ${meters(toNext)}`}
          />
        ) : null}
        <div className="walk__top-right">
          {phase !== 'preview' && (
            <button type="button" className="round-btn" onClick={toggleMute} aria-label={muted ? 'Unmute voice' : 'Mute voice'}>
              <Icon name={muted ? 'volumeOff' : 'volume'} size={20} />
            </button>
          )}
        </div>
      </div>
      {((state.replay && phase !== 'preview') || !live) && (
        <div className="walk__tape">
          <DemoTape label={state.replay && phase !== 'preview' ? `${demoLabel}DEMO · GPS REPLAY · ×${timeScale}` : 'SIMULATED DEMO'} />
        </div>
      )}
      {gpsError && <div className="walk__toast">{gpsError}</div>}
      {justSwitched && !gpsError && <div className="walk__toast walk__toast--ok" role="status">{plan?.reason ?? 'Switched to the new route.'}</div>}

      {/* ---------- sheets ---------- */}
      {phase === 'preview' && (
        <Sheet label={`Route offer from ${PERSONA.guide}`}>
          <div className="speaker">
            <Mascot agent="guide" state={plan ? 'talking' : 'thinking'} />
            <div>
              <div className="t-headline">{PERSONA.guide}</div>
              <div className="t-caption">{plan ? 'Planned before you left · just now' : 'Asking who is open nearby…'}</div>
            </div>
            <span style={{ marginLeft: 'auto' }}>
              <LinkBadge status={status} />
            </span>
          </div>
          <p className="t-spoken">{plan?.reason ?? 'Checking lights and open places along the route…'}</p>
          <div className="ticket">
            <div>
              <div className="t-number ticket__v">{Math.round(stats.hootroute.minutes)} MIN</div>
              <div className="ticket__k">arrive by {timeOf(arrive)}</div>
            </div>
            <div>
              <div className="t-number ticket__v" style={{ color: 'var(--route)' }}>
                {stats.hootroute.score} vs {stats.shortest.score}
              </div>
              <div className="ticket__k">street score</div>
            </div>
            <div>
              <div className="t-number ticket__v">+{(stats.hootroute.minutes - stats.shortest.minutes).toFixed(1)} MIN</div>
              <div className="ticket__k">extra walking</div>
            </div>
          </div>
          <div className="legend">
            <span><i className="legend__solid" /> {BRAND} route</span>
            <span><i className="legend__dots" /> Shortest path on our map</span>
          </div>
          <div className="btn-row">
            <Button kind="secondary" onClick={() => go('usual')}>Keep usual</Button>
            <Button kind="primary" onClick={() => go('hootroute')}>Go this way</Button>
          </div>
        </Sheet>
      )}

      {phase === 'walking' && (
        <Sheet label="Walk">
          <Steps at={3} />
          <div className="walk__eta">
            <div>
              <div className="t-number" style={{ fontSize: 22 }}>HOME {timeOf(arrive).replace(' PM', '').replace(' AM', '')}</div>
              <div className="t-caption">{Math.max(1, Math.round(etaMin))} min · {meters(remaining)}</div>
            </div>
            <div className="guardian-chip">
              <Initials text={guardianName[0]} />
              {!sharing ? 'Sharing stopped' : `${guardianFirst} ${state.guardianJoined ? 'is watching' : 'gets a live link if needed'}`}
            </div>
          </div>
          <hr className="divider" />
          {lowDistraction && <p className="t-caption" style={{ margin: 0 }}>Low-distraction guidance: turn prompts and check-ins only.</p>}
          {state.say && (!lowDistraction || state.say.agent === 'guide' || state.say.agent === 'rescuer') && (
            <>
              <div className="speaker">
                <Mascot agent={state.say.agent} state={now - state.say.ts < 4000 ? 'talking' : 'idle'} />
                <div>
                  <div className="t-headline">{AGENT_LABEL[state.say.agent]}</div>
                  <div className="t-caption">{now - state.say.ts < 4000 ? 'speaking now' : `${Math.round((now - state.say.ts) / 1000)} s ago`}</div>
                </div>
              </div>
              <p className="t-spoken" aria-live="polite">{state.say.text}</p>
            </>
          )}
          <div className="listening">
            {listener.current ? <Wave /> : <Icon name="mic" size={16} />}
            <span className="t-caption">{listener.current ? 'Listening — say "I\'m fine" or "help" anytime' : 'Voice replies aren\'t available here — use the buttons'}</span>
          </div>
          <div className="btn-row">
            <Button kind="fine" icon="check" onClick={() => reply('fine')}>I'm fine</Button>
            <HoldButton onConfirm={() => reply('help')}>Hold for help</HoldButton>
          </div>
          {live && ownsWalk && (
            <>
              <div className="lj__actions">
                <button type="button" className="lj__report" onClick={() => setReportOpen(true)}><Icon name="ring" size={16} /> Report a problem</button>
                {state.lastReport && !state.recovery && now - state.lastReport.ts < 60000 && <span className="t-caption">{SHORT.guide} is looking for other ways…</span>}
              </div>
              <SharingControl walkId={walkId} active={sharing} onChange={(v) => setShareLocal({ v, ts: Date.now() })} />
            </>
          )}
          {live && <button type="button" className="walk__end t-caption" onClick={endWalk}>End walk · stop sharing location</button>}
        </Sheet>
      )}

      {phase === 'checkin' && state.checkin && (
        <CheckIn
          checkin={state.checkin}
          now={now}
          guardian={guardianFirst}
          sharing={sharing}
          onFine={() => reply('fine')}
          onHelp={() => reply('help')}
        />
      )}

      {phase === 'escalated' && (
        <Sheet label="Guardian alerted">
          <div className="speaker">
            <Mascot agent="rescuer" state="talking" size={56} />
            <div>
              <div className="t-caption">{PERSONA.rescuer}</div>
              <h2 className="t-display" style={{ fontSize: 26, lineHeight: '30px' }}>{sharing ? `${guardianFirst} has your live location` : 'Sharing is stopped'}</h2>
            </div>
          </div>
          {!sharing && <p className="t-caption" style={{ margin: 0 }}>Your guardian link is revoked, so {guardianFirst} can't see your position and no text or call goes out. Turn sharing back on to send a new link.</p>}
          {live && ownsWalk && !sharing && <SharingControl walkId={walkId} active={sharing} onChange={(v) => setShareLocal({ v, ts: Date.now() })} />}
          <div className={`ack ${state.alert?.ackBy ? 'ack--on' : ''}`}>
            <Icon name={state.alert?.ackBy ? 'check' : 'ring'} size={18} />
            {state.alert?.ackBy ? `${guardianFirst} is on it` : `Waiting for ${guardianFirst} to respond…`}
          </div>
          <RescueLadder ladder={state.ladder} />
          <Button kind="fine" icon="check" tall block onClick={() => reply('fine')}>I'm okay now</Button>
          <Call911 />
          <p className="t-caption center">{BRAND} never dials 911 by itself. If you need emergency help, tap Call 911.</p>
        </Sheet>
      )}

      {phase === 'arrived' && (
        <Sheet label="Arrived">
          <Steps at={4} />
          <div className="speaker">
            <Mascot agent="head" state="done" size={56} />
            <div>
              <div className="t-caption">{PERSONA.head}</div>
              <h2 className="t-display" style={{ fontSize: 28 }}>You've arrived.</h2>
            </div>
          </div>
          <p className="t-caption" style={{ fontSize: 15, lineHeight: '21px' }}>{state.summary}</p>
          {state.reportBy && <p className="t-caption" style={{ fontSize: 11 }}>Walk report by {state.reportBy}. Numbers come from the engine and the walk log.</p>}
          {!live && <p className="t-caption" style={{ fontSize: 11 }}>Simulated demo: the agents were played by the offline demo engine.</p>}
          <div className="btn-row">
            <Button kind="secondary" onClick={() => nav(`/room?walk=${walkId}`)}>Control room</Button>
            <Button kind="primary" onClick={() => { if (isLive()) { nav('/plan'); return; } send({ type: 'walk.reset' }); engine.current?.plan(); }}>New walk</Button>
          </div>
        </Sheet>
      )}

      {live && ownsWalk && <ReportSheet open={reportOpen} onClose={() => setReportOpen(false)} send={send} at={state.position?.lngLat} />}
      {recovery && <RecoverySheet r={recovery} now={now} send={send} onDismiss={() => setDismissed(recovery.recoveryId)} />}
    </div>
  );
}

function CheckIn({ checkin, now, guardian, sharing, onFine, onHelp }: { checkin: NonNullable<ReturnType<typeof useWalk>['state']['checkin']>; now: number; guardian: string; sharing: boolean; onFine: () => void; onHelp: () => void }) {
  const span = Math.max(1, checkin.deadline - checkin.ts);
  const left = Math.max(0, checkin.deadline - now);
  const frac = left / span;
  const secs = Math.ceil(frac * checkin.windowSec);
  return (
    <Sheet label="Check-in" className="checkin">
      <div className="countdown">
        <div className="countdown__row">
          <span className="t-number" style={{ color: 'var(--checkin)', letterSpacing: 1 }}>CHECKING IN</span>
          <span className="t-number">{Math.floor(secs / 60)}:{String(secs % 60).padStart(2, '0')} left</span>
        </div>
        <div className="countdown__track">
          <div className="countdown__fill" style={{ transform: `scaleX(${frac})` }} />
        </div>
      </div>
      <div className="speaker">
        <Mascot agent="checker" state="talking" size={64} />
        <div>
          <div className="t-caption">{PERSONA.checker}</div>
          <h2 className="t-display">{checkin.text}</h2>
        </div>
      </div>
      <p className="muted" style={{ margin: 0, fontSize: 15 }}>Why I'm asking: {checkin.reason.charAt(0).toLowerCase() + checkin.reason.slice(1)}</p>
      <Button kind="fine" icon="check" tall block onClick={onFine}>I'm fine</Button>
      <HoldButton block onConfirm={onHelp}>Hold for help</HoldButton>
      <p className="t-caption center">{sharing ? `No answer in ${secs} s → ${guardian} is alerted on the live link.` : 'Sharing is stopped, so nobody is alerted if you don’t answer.'} {BRAND} never calls 911 for you.</p>
    </Sheet>
  );
}

function Wave() {
  return (
    <span className="wave" aria-hidden>
      {[4, 10, 16, 8, 14, 6, 2].map((h, i) => (
        <i key={i} style={{ height: h, animationDelay: `${i * 90}ms` }} />
      ))}
    </span>
  );
}
