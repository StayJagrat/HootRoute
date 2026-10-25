import { useEffect, useMemo, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { api } from '../api/client'
import { Avatar } from '../components/Avatar'
import { MapView } from '../components/MapView'
import { cumulative, fmtClock, pointAt } from '../lib/geo'
import { closeTime } from '../lib/text'
import { listen, speak, voiceSupported } from '../lib/voice'
import { selectedRoute, useApp } from '../state/store'

type Status = 'walking' | 'checkin' | 'alert' | 'escalated' | 'arrived'
const SPEED_SECONDS = 55           // the replay covers the whole route in about a minute
const STOP_FACTOR = 15             // simulated seconds per real second while stopped (90 s becomes 6 s)
const REPLY_FACTOR = 5             // simulated seconds per real second while waiting for a reply (45 s becomes 9 s)

function Arrow({ m }: { m: string }) {
  const rot = m.includes('left') ? (m.includes('slight') ? -45 : -90) : m.includes('right') ? (m.includes('slight') ? 45 : 90) : 0
  return <svg className="arrow" viewBox="0 0 24 24" style={{ transform: `rotate(${rot}deg)` }} aria-hidden="true"><path d="M12 3l6 7h-4v11h-4V10H6z" fill="currentColor" /></svg>
}

export function Walk() {
  const { walk, resp, minute, guardian, walker, replySec, go, plan } = useApp()
  const route = selectedRoute(useApp.getState())!
  const cum = useMemo(() => cumulative(walk!.coords), [walk!.id])
  const total = cum[cum.length - 1]
  const [d, setD] = useState(0); const [status, setStatus] = useState<Status>('walking'); const [msg, setMsg] = useState(''); const [since, setSince] = useState<number | null>(null)
  const [hold, setHold] = useState(0); const [voiceOn, setVoiceOn] = useState(true); const [listening, setListening] = useState(false)
  const R = useRef({ d: 0, prev: 0, stopped: 0, since: null as number | null, replied: false, status: 'walking' as Status, quietUntil: 0, tickAcc: 0, quiet: false, arrived: false })
  const stopped = useApp((s) => s.walk?.sim.stopped) ?? false
  const wid = walk!.id; const pos = pointAt(walk!.coords, cum, d)

  const setSt = (s: Status) => { R.current.status = s; setStatus(s) }
  const say = (t: string) => { setMsg(t); if (voiceOn) speak(t) }

  const imFine = async () => {
    const r = R.current
    if (r.status === 'checkin' || r.status === 'alert') { r.replied = true; r.since = null; setSince(null); r.stopped = 0; useApp.getState().patchWalk({ sim: { playing: true, stopped: false } } as any); setSt('walking') }
    else if (r.status === 'escalated') { await api(`/api/walk/${wid}/clear`, { method: 'POST' }); r.since = null; setSince(null); r.stopped = 0; useApp.getState().patchWalk({ sim: { playing: true, stopped: false } } as any); setSt('walking'); say("Glad you're okay. Continuing the walk.") }
    else say('Noted. I will keep watching.')
  }
  const help = async () => { await api(`/api/walk/${wid}/help`, { method: 'POST' }); setSt('escalated'); say(`${guardian} has your live position. I am staying with you. I do not call 911.`) }

  // listen for "I'm fine" and "help" by voice where the browser supports it
  useEffect(() => { if (!voiceSupported) return; setListening(true); return listen(() => imFine(), () => help()) }, [wid])

  // the replay loop
  useEffect(() => {
    let raf = 0, last = performance.now(), uiAcc = 0
    const speed = total / SPEED_SECONDS
    const loop = (now: number) => {
      const dt = Math.min(0.1, (now - last) / 1000); last = now; const r = R.current; const isStopped = useApp.getState().walk?.sim.stopped ?? false
      if (!r.arrived) {
        if (!isStopped && r.status === 'walking') { r.prev = r.d; r.d = Math.min(total, r.d + speed * dt) }
        else if (isStopped) {
          r.stopped += dt * STOP_FACTOR
          if (r.since !== null) { r.since += dt * REPLY_FACTOR }
        }
        r.tickAcc += dt
        if (r.tickAcc >= 0.7) {
          r.tickAcc = 0
          api<{ decision: { decision: string; msg: string }; status: string }>('/api/walk/tick', { method: 'POST', json: { walk_id: wid, d: r.d, prev_d: r.prev, stopped_s: r.stopped, since_checkin_s: r.since, replied: r.replied } }).then((res) => {
            const dc = res.decision.decision; r.replied = false
            if (dc === 'checkin' && r.status === 'walking') { r.since = 0; setSt('checkin'); say(res.decision.msg) }
            else if (dc === 'alert' && r.status !== 'alert' && r.status !== 'escalated') { setSt('alert'); say(res.decision.msg) }
            else if (dc === 'escalate' && r.status !== 'escalated') { setSt('escalated'); say(res.decision.msg) }
            else if (dc === 'quiet' && now > r.quietUntil) { r.quietUntil = now + 4000; say(res.decision.msg); setTimeout(() => { r.stopped = 0; useApp.getState().patchWalk({ sim: { playing: true, stopped: false } } as any) }, 2200) }
            else if (dc === 'info' || dc === 'ok') say(res.decision.msg)
          }).catch(() => { /* the replay keeps going if a tick fails */ })
        }
        if (r.d >= total - 1 && !r.arrived) { r.arrived = true; setSt('arrived'); api(`/api/walk/${wid}/finish`, { method: 'POST' }).catch(() => {}); say('You are home. I saved a draft report. Nothing was submitted.') }
        uiAcc += dt; if (uiAcc > 0.1) { uiAcc = 0; setD(r.d); setSince(r.since) }
      }
      raf = requestAnimationFrame(loop)
    }
    raf = requestAnimationFrame(loop); return () => cancelAnimationFrame(raf)
  }, [wid])

  // next maneuver and the next open place ahead
  const steps = walk!.steps; const next = steps.find((s) => s.at_m > d + 5); const toTurn = next ? Math.max(10, Math.round((next.at_m - d) / 10) * 10) : 0
  const ahead = walk!.shops.filter((s) => s.d >= d - 10).sort((a, b) => a.d - b.d)[0]
  const idle = ahead ? `${ahead.name || ahead.cat} ahead${closeTime(ahead.hours) ? `, open till ${closeTime(ahead.hours)}` : ''}. ` : ''
  const guide = next ? `${idle}${next.maneuver === 'continue' ? 'Continue' : next.maneuver[0].toUpperCase() + next.maneuver.slice(1)} on ${next.street} in about ${toTurn} metres.` : 'Your destination is just ahead.'
  const remaining = Math.max(0, Math.round(((total - d) / total) * walk!.minutes))

  // hold for help
  const holdRef = useRef<number | null>(null)
  const startHold = () => { const t0 = performance.now(); const tick = (n: number) => { const p = Math.min(1, (n - t0) / 1100); setHold(p); if (p >= 1) { setHold(0); holdRef.current = null; help() } else holdRef.current = requestAnimationFrame(tick) }; holdRef.current = requestAnimationFrame(tick) }
  const endHold = () => { if (holdRef.current) cancelAnimationFrame(holdRef.current); holdRef.current = null; setHold(0) }

  return (
    <div className="screen">
      <MapView routes={[route]} selected={route.id} walker={pos.ll} follow bearing={pos.bearing} pad={{ top: 190, bottom: 0, left: 0, right: 0 }} />
      <div className="scrim-top" />
      {next && (
        <motion.div className="turn" key={next.at_m} initial={{ y: -20, opacity: 0 }} animate={{ y: 0, opacity: 1 }}>
          <Arrow m={next.maneuver} /><div><b>{next.street}</b><span>{next.maneuver === 'continue' ? 'Continue' : `Turn ${next.maneuver}`}, {toTurn} m</span></div>
        </motion.div>
      )}
      <div className="demo-strip"><span>DEMO</span> GPS REPLAY</div>
      {(status === 'alert' || status === 'escalated') && <div className="pulse-ring" />}
      <div className="sheet" style={{ maxHeight: '58%' }}>
        <div className="row" style={{ justifyContent: 'space-between' }}>
          <div><div className="label">Home {fmtClock(minute + walk!.minutes).replace(':00', '')}</div><b style={{ fontFamily: 'var(--sw-font-display)', fontSize: 22 }}>{remaining} min</b></div>
          <span className="chip" style={{ cursor: 'pointer' }} onClick={() => setVoiceOn((v) => !v)} role="button" aria-pressed={voiceOn}>{voiceOn ? 'Voice on' : 'Voice off'}</span>
          <span className={`chip ${status === 'walking' ? 'ok' : 'danger'}`}>{status === 'walking' ? `${guardian} is watching` : status === 'escalated' ? `${guardian} alerted` : status === 'alert' ? `Alerting ${guardian}` : status === 'arrived' ? 'Arrived' : 'Checking in'}</span>
        </div>
        <div className="bubble"><Avatar agent="watcher" /><div className="grow"><div><span className="who">Watcher</span> <span className="when">speaking now</span></div><p className="say" style={{ marginTop: 4 }}>{msg || guide}</p></div></div>
        <div className="row" style={{ fontSize: 13, color: 'var(--sw-muted)' }}>
          <span className="wave" aria-hidden="true">{Array.from({ length: 9 }).map((_, i) => <i key={i} />)}</span>
          <span>{listening ? <>Listening, say &ldquo;I&rsquo;m fine&rdquo; or &ldquo;help&rdquo; anytime</> : <>Tap a button to answer. Voice replies need a supported browser.</>}</span>
        </div>
        <div className="row">
          <button className="btn ok grow" onClick={imFine}>✓ I&rsquo;m fine</button>
          <button className="btn danger grow hold" onPointerDown={startHold} onPointerUp={endHold} onPointerLeave={endHold} onClick={(e) => e.preventDefault()}><i style={{ width: `${hold * 100}%` }} />Hold for help</button>
        </div>
      </div>
      <AnimatePresence>
        {status === 'checkin' && (
          <motion.div className="checkin" initial={{ y: 400 }} animate={{ y: 0 }} exit={{ y: 400 }} transition={{ type: 'spring', stiffness: 200, damping: 24 }}>
            <div className="label" style={{ color: 'var(--sw-warn)' }}>Checking in</div>
            <div className="bubble"><Avatar agent="watcher" size="lg" /><div className="big">You stopped. All good?</div></div>
            <p style={{ fontSize: 13, color: 'var(--sw-muted)' }}>Why I&rsquo;m asking: you stopped for {useApp.getState().stopSec} s on a stretch with no open place nearby.</p>
            <div className="countbar"><i style={{ width: `${Math.max(0, 100 - ((since ?? 0) / replySec) * 100)}%` }} /></div>
            <button className="btn ok block" onClick={imFine}>✓ I&rsquo;m fine</button>
            <button className="btn danger block" onClick={help}>Hold for help</button>
            <p style={{ fontSize: 12, color: 'var(--sw-muted)', textAlign: 'center' }}>No answer in {replySec} s and I send {guardian} your live position. I don&rsquo;t call 911.</p>
          </motion.div>
        )}
        {status === 'escalated' && (
          <motion.div className="checkin" initial={{ y: 400 }} animate={{ y: 0 }} exit={{ y: 400 }}>
            <div className="label" style={{ color: 'var(--sw-danger)' }}>{guardian} alerted</div>
            <div className="big" style={{ fontSize: 28 }}>{guardian} can see where you are.</div>
            <p style={{ fontSize: 14, color: 'var(--sw-muted)' }}>Handoff packet written (position, route, time, reason). Streetwise did not contact emergency services. If you are in danger, call 911 yourself.</p>
            <button className="btn ok block" onClick={imFine}>I&rsquo;m okay now</button>
          </motion.div>
        )}
        {status === 'arrived' && (
          <motion.div className="checkin" initial={{ y: 400 }} animate={{ y: 0 }}>
            <div className="label" style={{ color: 'var(--sw-ok)' }}>Arrived</div>
            <div className="big">{walker}, you&rsquo;re home.</div>
            <p style={{ fontSize: 14, color: 'var(--sw-muted)' }}>Reporter saved a draft report. Nothing was submitted to the city. Night Auditor will re-score these blocks tonight.</p>
            <button className="btn primary block" onClick={async () => { useApp.setState({ walk: null }); await plan(); go('preview') }}>Plan another walk</button>
          </motion.div>
        )}
      </AnimatePresence>
      <span style={{ display: 'none' }}>{resp?.candidates}</span>
    </div>
  )
}
