import { useEffect } from 'react'
import { Avatar } from './components/Avatar'
import { ControlRoom } from './screens/ControlRoom'
import { GuardianPage } from './screens/Guardian'
import { Preview } from './screens/Preview'
import { Setup } from './screens/Setup'
import { ShopPage } from './screens/Shop'
import { Walk } from './screens/Walk'
import { api } from './api/client'
import { useApp } from './state/store'

function PhoneApp() {
  const { init, screen, walk, meta, session } = useApp()
  useEffect(() => { init().then(() => useApp.getState().plan()) }, [])
  const stopped = walk?.sim.stopped
  const suggest = async () => { const s = await api<{ id: string; name: string }[]>('/api/agents/place/suggest', { method: 'POST', json: { session } }); if (s[0]) window.open(`/shop/${s[0].id}`, '_blank') }
  return (
    <div className="stage">
      <div className="phone">
        <div className="statusbar"><span>11:04</span><span>5G ▮▮▮</span></div>
        {screen === 'setup' && <Setup />}
        {screen === 'preview' && <Preview />}
        {screen === 'walk' && walk && <Walk />}
      </div>
      <aside className="demo">
        <div className="label">Demo controls</div>
        {screen === 'walk' && walk ? (<>
          <button className={`btn ${stopped ? 'ok' : 'danger'}`} onClick={() => useApp.getState().patchWalk({ sim: { playing: true, stopped: !stopped } } as any)}>{stopped ? 'Keep walking' : 'Stop here (simulate)'}</button>
          <a className="btn" href={`/guardian/${walk.id}`} target="_blank" rel="noreferrer">Open guardian page</a>
        </>) : <p style={{ fontSize: 12, color: 'var(--sw-muted)' }}>Press &ldquo;Go this way&rdquo; to start the walk replay.</p>}
        <button className="btn" onClick={suggest} disabled={!useApp.getState().resp}>Open a shop page</button>
        <a className="btn" href="/room" target="_blank" rel="noreferrer">Open control room</a>
        <button className="btn" onClick={() => useApp.getState().reset()}>Reset demo</button>
        <div className="row" style={{ marginTop: 6 }}><Avatar agent="scout" /><span style={{ fontSize: 12, color: 'var(--sw-muted)' }}>{meta ? `${meta.stats.places} places · ${meta.stats.lamp_points} lamp points` : 'loading data'}</span></div>
      </aside>
    </div>
  )
}

export default function App() {
  const p = location.pathname
  const g = p.match(/^\/guardian\/([^/]+)/), s = p.match(/^\/shop\/([^/]+)/)
  if (g) return <GuardianPage id={g[1]} />
  if (s) return <ShopPage id={s[1]} />
  if (p.startsWith('/room')) return <ControlRoom />
  return <PhoneApp />
}
