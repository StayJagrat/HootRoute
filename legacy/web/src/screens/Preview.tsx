import { useEffect, useMemo, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { Avatar } from '../components/Avatar'
import { MapView } from '../components/MapView'
import { fmtClock } from '../lib/geo'
import { homeBy, scoutLine } from '../lib/text'
import { selectedRoute, useApp } from '../state/store'

const LABEL: Record<string, string> = { places: 'Open places along the route', gaps: 'Gaps between open places', help: 'Open help points nearby', light: 'Street lighting', main: 'Main roads', transit: 'Transit running at your time', turns: 'Fewer turns' }

export function Preview() {
  const { resp, origin, dest, minute, day, select, selected, startWalk, go, loading, error } = useApp()
  const [draw, setDraw] = useState(0); const [open, setOpen] = useState(false)
  const fast = resp?.routes.find((r) => r.id === 'fast'), best = resp?.routes.find((r) => r.id === 'best') || fast
  useEffect(() => { if (!resp) return; setDraw(0); let raf = 0; const t0 = performance.now(); const tick = (n: number) => { const p = Math.min(1, (n - t0) / 1600); setDraw(1 - Math.pow(1 - p, 3)); if (p < 1) raf = requestAnimationFrame(tick) }; raf = requestAnimationFrame(tick); return () => cancelAnimationFrame(raf) }, [resp])
  const markers = useMemo(() => {
    const r = best; if (!r) return []
    return [{ ll: r.coords[0], cls: 'col', html: `<div class="pin" style="background:#6fa8ff">A</div><div class="tag side">${fmtClock(minute)} · leaving ${origin?.label ?? ''}</div>` },
            { ll: r.coords[r.coords.length - 1], cls: 'col', html: `<div class="pin" style="background:#ff6b5a">B</div>` }]
  }, [best, origin, minute])
  const route = selectedRoute(useApp.getState())
  if (!resp || !best || !fast) return <div className="screen"><div className="pad" style={{ justifyContent: 'center', alignItems: 'center' }}><p>{loading ? 'Scoring every block…' : error ?? 'No route yet.'}</p></div></div>
  const delta = best.minutes - fast.minutes
  return (
    <div className="screen">
      <MapView routes={resp.routes} selected={selected} draw={draw} markers={markers} pad={{ top: 90, bottom: 440, left: 34, right: 34 }} />
      <div className="scrim-top" />
      <motion.div className="sheet" initial={{ y: 380 }} animate={{ y: 0 }} transition={{ type: 'spring', stiffness: 160, damping: 22, delay: 0.5 }}>
        <div className="bubble"><Avatar agent="scout" /><div className="grow"><div><span className="who">Scout</span> <span className="when">Planned before you left, just now</span></div><p className="say" style={{ marginTop: 4 }}>{scoutLine(best, fast)}</p></div></div>
        <div className="stats">
          <div><b>{Math.round(best.minutes)}</b><span>min · home by {homeBy(minute, best.minutes).replace(':00', '')}</span></div>
          <div><b style={{ color: 'var(--sw-primary)' }}>{Math.round(best.score)} vs {Math.round(fast.score)}</b><span>street score</span></div>
          <div><b>{delta >= 0 ? '+' : ''}{delta.toFixed(1)}</b><span>min extra walking</span></div>
        </div>
        <div className="legend"><span><i />Streetwise route</span><span><i className="dot" />Shortest path on our map</span></div>
        <button className="chip" style={{ background: 'transparent', cursor: 'pointer', alignSelf: 'flex-start' }} onClick={() => setOpen((o) => !o)} aria-expanded={open}>{open ? 'Hide' : 'Why this score?'}</button>
        <AnimatePresence initial={false}>{open && (
          <motion.div className="breakdown" initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={{ height: 0, opacity: 0 }} style={{ overflow: 'hidden' }}>
            {Object.keys(LABEL).map((k) => <div className="r" key={k}><span>{LABEL[k]}</span><b>{route!.points[k].toFixed(1)} / {route!.weights[k]}</b><div className="bar"><i style={{ width: `${(route!.points[k] / route!.weights[k]) * 100}%` }} /></div></div>)}
            <p style={{ fontSize: 12, color: 'var(--sw-muted)', marginTop: 8 }}>Conditions at the minute you pass each block, compared with typical walks here at this hour. Not a safety rating. {route!.unknown_hours_nearby} places nearby have no listed hours and count as closed.</p>
          </motion.div>)}
        </AnimatePresence>
        <div className="row">
          <button className="btn grow" onClick={() => { select('fast'); startWalk() }}>Keep usual</button>
          <button className="btn primary grow" onClick={() => { select('best'); startWalk() }}>Go this way</button>
        </div>
        <button className="chip" style={{ background: 'transparent', cursor: 'pointer', alignSelf: 'center' }} onClick={() => go('setup')}>Back to standing orders</button>
        <span style={{ display: 'none' }}>{day}</span>
      </motion.div>
    </div>
  )
}
