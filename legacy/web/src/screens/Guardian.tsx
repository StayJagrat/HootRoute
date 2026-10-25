import { useEffect, useMemo, useState } from 'react'
import { api, subscribe } from '../api/client'
import type { Route, WalkState } from '../api/types'
import { MapView } from '../components/MapView'
import { cumulative, fmtClock, pointAt } from '../lib/geo'

interface Live { status: WalkState['status']; d: number; ll: WalkState['ll']; last_checkin: string }

export function GuardianPage({ id }: { id: string }) {
  const [w, setW] = useState<WalkState | null>(null); const [live, setLive] = useState<Live | null>(null); const [err, setErr] = useState(''); const [details, setDetails] = useState(false)
  const load = () => api<WalkState>(`/api/walk/${id}`).then((x) => { setW(x); setLive({ status: x.status, d: x.d, ll: x.ll, last_checkin: x.last_checkin }) }).catch((e) => setErr(String(e)))
  useEffect(() => { load(); const t = setInterval(load, 2500); const off = subscribe(`walk-${id}`, (e) => { if (e.agent === 'walk' && e.data?.status) setLive((p) => ({ status: e.data.status, d: e.data.d ?? p?.d ?? 0, ll: e.data.ll ?? p?.ll ?? [0, 0], last_checkin: e.data.last_checkin ?? p?.last_checkin ?? '' })) }); return () => { clearInterval(t); off() } }, [id])
  const cum = useMemo(() => (w ? cumulative(w.coords) : [0]), [w?.id])
  const route = useMemo(() => (w ? ({ id: 'best', label: 'Route', score: w.score, coords: w.coords, shops: w.shops, gap: w.gap, steps: w.steps, minutes: w.minutes, km: w.km } as unknown as Route) : null), [w?.id])
  if (err) return <div className="stage"><div className="phone day"><div className="pad"><h1 className="title">This link has expired</h1><p>The walk ended or the link is not valid.</p></div></div></div>
  if (!w || !live || !route) return <div className="stage"><div className="phone day"><div className="pad"><p>Opening the live link…</p></div></div></div>
  const alert = live.status === 'alert' || live.status === 'escalated'; const left = Math.max(0, Math.round(((cum[cum.length - 1] - live.d) / cum[cum.length - 1]) * w.minutes))
  const street = [...w.steps].reverse().find((s) => s.at_m <= live.d)?.street ?? 'the route'
  const clear = async () => { await api(`/api/walk/${id}/clear`, { method: 'POST' }); load() }
  return (
    <div className="stage"><div className="phone day">
      <div className="screen">
        <MapView mode="day" routes={[route]} selected="best" walker={live.ll} pad={{ top: 120, bottom: 330, left: 24, right: 24 }} showShops={false} />
        <div style={{ position: 'absolute', top: 16, left: 14, right: 14, zIndex: 6 }}>
          <div className="card row" style={{ padding: '10px 14px' }}><div className="grow"><b style={{ fontFamily: 'var(--sw-font-display)', fontSize: 18 }}>streetwise</b><div style={{ fontSize: 12, color: 'var(--sw-day-muted)' }}>Shared by {w.walker}. Ends when the walk ends.</div></div><span className="livepill"><i />LIVE</span></div>
        </div>
        <div className="sheet" style={{ gap: 14 }}>
          <div><h1 style={{ fontFamily: 'var(--sw-font-display)', fontSize: 26, fontWeight: 800 }}>{live.status === 'arrived' ? `${w.walker} is home` : `${w.walker} is walking home`}</h1><div style={{ color: 'var(--sw-day-muted)', fontSize: 14 }}>{live.status === 'arrived' ? 'The walk is over and sharing has stopped.' : `${left} min away · checked in ${live.last_checkin === 'Not yet' ? 'not yet' : '2 min ago'}`}</div></div>
          <div className="card kv"><span>Route</span><span>Via {street}</span><span>Last check-in</span><span>{live.last_checkin}</span><span>Arrives</span><span>Home · {fmtClock(w.req.minute + w.minutes).replace(':00', '')}</span></div>
          <p style={{ fontSize: 12, color: 'var(--sw-day-muted)' }}>If {w.walker} stops answering, you will see a full-screen alert here. Location sharing stops when the walk ends.</p>
          <button className="btn primary" onClick={() => alertText()}>Call {w.walker}</button>
        </div>
        {alert && (
          <div className="alertscreen" role="alertdialog" aria-label="Alert">
            <div className="row" style={{ fontFamily: 'var(--sw-font-mono)', fontSize: 11, letterSpacing: '0.1em' }}>STREETWISE ALERT · {fmtClock(w.req.minute + (live.d / cum[cum.length - 1]) * w.minutes)}</div>
            <h1>{w.walker} isn&rsquo;t answering</h1>
            <p style={{ opacity: 0.92 }}>No reply for 90 s. Last seen on {street}.</p>
            <div style={{ borderRadius: 16, overflow: 'hidden', height: 190, position: 'relative', flex: '0 0 auto' }}><MapView mode="day" routes={[route]} selected="best" walker={live.ll} showShops={false} interactive={false} pad={{ top: 20, bottom: 20, left: 20, right: 20 }} /></div>
            <button className="btn light" onClick={() => alertText()}>Call {w.walker}</button>
            <button className="btn dark" onClick={clear}>I&rsquo;m on it, clear the alert</button>
            <button className="chip" style={{ background: 'transparent', color: '#fff', borderColor: 'rgba(255,255,255,0.4)', alignSelf: 'center' }} onClick={() => setDetails((v) => !v)}>See details (position, route, time, reason)</button>
            {details && <div className="kv" style={{ background: 'rgba(0,0,0,0.2)', padding: 12, borderRadius: 12, color: '#fff' }}><span style={{ color: '#ffd' }}>Position</span><span>{live.ll[1].toFixed(5)}, {live.ll[0].toFixed(5)}</span><span style={{ color: '#ffd' }}>Route</span><span>{w.steps.map((s) => s.street).filter((v, i, a) => a.indexOf(v) === i).slice(0, 3).join(' → ')}</span><span style={{ color: '#ffd' }}>Reason</span><span>Stopped, no reply</span></div>}
            <div className="grow" />
            <p style={{ fontSize: 12, opacity: 0.9, textAlign: 'center' }}>Streetwise does not call 911. If you think {w.walker} is in danger, call 911 yourself.</p>
          </div>
        )}
      </div>
    </div></div>
  )
  function alertText() { window.alert('Calling is not connected in this demo. In production this opens the phone dialer.') }
}
