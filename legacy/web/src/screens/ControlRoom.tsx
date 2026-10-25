import { useEffect, useMemo, useState } from 'react'
import { api } from '../api/client'
import type { DebtRow, Route, RouteResponse, WhyStreet } from '../api/types'
import { Avatar, AGENT_NAME } from '../components/Avatar'
import { MapView } from '../components/MapView'
import { cumulative, fmtClock } from '../lib/geo'
import { DEMO, useApp } from '../state/store'

interface SessionState { route: RouteResponse | null; req: { minute: number } | null; walk: { id: string; status: string; d: number; ll: [number, number]; walker: string; guardian: string; last_checkin: string; route_id: string } | null }
const TABS = [['live', 'Live walk'], ['agents', 'Agents'], ['city', 'City ranking'], ['audit', 'Overnight audit']] as const
const time = (ts: number) => new Date(ts * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })

export function ControlRoom() {
  const { init, events, meta, session } = useApp()
  const [st, setSt] = useState<SessionState | null>(null); const [tab, setTab] = useState<(typeof TABS)[number][0]>('live'); const [why, setWhy] = useState<WhyStreet | null>(null)
  const [debt, setDebt] = useState<{ rows: DebtRow[]; walkers: number; note: string } | null>(null); const [audit, setAudit] = useState<Record<string, any> | null>(null)
  useEffect(() => { init(); api<typeof debt>('/api/debt').then(setDebt).catch(() => {}); const t = setInterval(() => api<SessionState>(`/api/session/${session}/state`).then(setSt).catch(() => {}), 1200); return () => clearInterval(t) }, [])
  const route: Route | undefined = st?.route?.routes.find((r) => r.id === (st.walk?.route_id ?? st.route?.recommended)) ?? st?.route?.routes[0]
  const walkLL = st?.walk?.ll ?? null
  useEffect(() => { if (!walkLL) return; const t = setTimeout(() => api<WhyStreet>(`/api/why?lat=${walkLL[1]}&lon=${walkLL[0]}&day=${DEMO.day}&minute=${DEMO.minute}`).then(setWhy).catch(() => {}), 300); return () => clearTimeout(t) }, [Math.round((walkLL?.[0] ?? 0) * 3000), Math.round((walkLL?.[1] ?? 0) * 3000)])
  const total = useMemo(() => (route ? cumulative(route.coords).slice(-1)[0] : 1), [route?.coords.length])
  const alerting = st?.walk && ['alert', 'escalated'].includes(st.walk.status)
  const feed = [...events].reverse().slice(0, 40)
  return (
    <div className="room">
      <aside>
        <div style={{ padding: '4px 10px 16px' }}><b style={{ fontFamily: 'var(--sw-font-display)', fontSize: 22 }}>streetwise</b><div className="label">control room</div></div>
        {TABS.map(([k, l]) => <button key={k} className={`navi ${tab === k ? 'on' : ''}`} onClick={() => setTab(k)}>{l}{k === 'live' && alerting && <span className="chip danger">1 alert</span>}</button>)}
        <div className="grow" />
        <div className="card" style={{ fontSize: 12 }}><b>Cached data</b><div style={{ color: 'var(--sw-muted)' }}>Scores, places and lamp evidence are stored locally, so the map and scoring keep working if the venue Wi-Fi drops. Live agents need a connection.</div></div>
        <button className="btn" onClick={() => useApp.getState().reset()}>Reset demo</button>
      </aside>
      <main>
        <div className="head">
          <div><h1 style={{ fontFamily: 'var(--sw-font-display)', fontSize: 24 }}>Friday · {fmtClock(st?.req?.minute ?? DEMO.minute)} scenario</h1><div style={{ color: 'var(--sw-muted)', fontSize: 13 }}>Downtown SF box · {meta?.stats.segments?.toLocaleString() ?? '…'} street segments scored</div></div>
          <div className="row wrap"><span className="chip primary">Apify · {meta?.stats.hours_filled ?? 0} hours filled</span><span className="chip">{meta?.stats.places_no_hours ?? '…'} places without hours</span><span className={`chip ${alerting ? 'danger' : 'ok'}`}>{st?.walk ? `walk ${st.walk.status}` : 'no walk yet'}</span></div>
        </div>
        <div className="mapbox">
          {route ? <MapView routes={st!.route!.routes} selected={route.id} walker={walkLL} pad={{ top: 60, bottom: 60, left: 60, right: 340 }} /> : <div style={{ display: 'grid', placeItems: 'center', height: '100%', color: 'var(--sw-muted)' }}>Plan a route on the phone app to see it here.</div>}
          <div className="float">
            {tab === 'live' && (<>
              <div className="card"><div className="label">Why this street</div>{why ? (<><div className="row" style={{ justifyContent: 'space-between' }}><b style={{ fontSize: 16 }}>{why.street}</b><b style={{ fontFamily: 'var(--sw-font-display)', fontSize: 30, color: why.score < 40 ? 'var(--sw-danger)' : 'var(--sw-ok)' }}>{why.score}</b></div><p style={{ fontSize: 13, color: 'var(--sw-muted)', marginTop: 4 }}>{why.text}</p></>) : <p style={{ fontSize: 13, color: 'var(--sw-muted)' }}>Start a walk to follow the walker block by block.</p>}</div>
              <div className="card debt"><div className="label">Darkness debt · modeled</div>{(debt?.rows ?? []).slice(0, 3).map((r, i) => <div className="r" key={r.street}><span>{r.street}</span><b className="mono">{r.minutes} min</b><i style={{ width: `${(r.minutes / (debt!.rows[0].minutes || 1)) * 100}%`, opacity: 1 - i * 0.2 }} /></div>)}<p style={{ fontSize: 11, color: 'var(--sw-muted)', marginTop: 8 }}>Walker-minutes on the weakest quarter of segments. Modeled walkers, not measured.</p></div>
            </>)}
            {tab === 'agents' && (['scout', 'place', 'watcher', 'rescuer', 'reporter', 'auditor'] as const).map((a) => <div className="card row" key={a}><Avatar agent={a} /><div className="grow"><b>{AGENT_NAME[a]}</b><div style={{ fontSize: 12, color: 'var(--sw-muted)' }}>{feed.filter((e) => e.agent === a).length} actions this session</div></div></div>)}
            {tab === 'city' && <div className="card debt"><div className="label">City ranking · where walking time is weakest</div>{(debt?.rows ?? []).map((r, i) => <div className="r" key={r.street}><span>{r.street}</span><b className="mono">{r.minutes} min</b><i style={{ width: `${(r.minutes / (debt!.rows[0].minutes || 1)) * 100}%`, opacity: 1 - i * 0.12 }} /></div>)}<p style={{ fontSize: 11, color: 'var(--sw-muted)', marginTop: 8 }}>{debt?.note}</p></div>}
            {tab === 'audit' && <div className="card"><div className="label">Overnight audit</div><button className="btn primary block" style={{ marginTop: 8 }} onClick={() => api<Record<string, any>>('/api/agents/auditor/run', { method: 'POST', json: { session } }).then(setAudit)}>Run the audit</button>{audit && <div style={{ fontSize: 13, marginTop: 10 }}><p>{audit.no_hours} of {audit.places} places have no listed hours.</p><p>{audit.lamp_evidence} lamp locations inferred from past 311 reports; {audit.open_outages} open outage reports subtracted.</p></div>}</div>}
          </div>
        </div>
        <div className="scrub">
          <div className="row" style={{ justifyContent: 'space-between' }}><span className="label">Replay · demo GPS</span><span className="mono" style={{ fontSize: 12, color: 'var(--sw-muted)' }}>{st?.walk ? `${Math.round(st.walk.d)} m of ${Math.round(total)} m` : 'waiting for a walk'}</span></div>
          <div className="track"><i className="fill" style={{ width: `${st?.walk ? Math.min(100, (st.walk.d / total) * 100) : 0}%` }} /><b style={{ left: '0%' }}><span>Start</span></b>{alerting && <b className="red" style={{ left: `${(st!.walk!.d / total) * 100}%` }}><span>Alert</span></b>}<b style={{ left: '100%' }}><span>Home</span></b></div>
        </div>
      </main>
      <section className="feed">
        <h2>Agent feed</h2>
        <div className="feedlist">{feed.length === 0 && <p style={{ fontSize: 13, color: 'var(--sw-muted)', padding: 8 }}>Agents report here as they work. Every line says why.</p>}
          {feed.map((e, i) => <div className="ev" key={e.ts + '-' + i}><Avatar agent={e.agent} /><div><div className="top"><span>{AGENT_NAME[e.agent] ?? e.agent}</span><time>{time(e.ts)}</time></div><p>{e.msg}</p>{e.data?.why && <div className="why">why: {e.data.why}</div>}</div></div>)}</div>
      </section>
    </div>
  )
}
