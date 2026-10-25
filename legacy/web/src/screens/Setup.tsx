import { motion } from 'framer-motion'
import { Avatar, AGENT_NAME } from '../components/Avatar'
import { useApp } from '../state/store'

export function Setup() {
  const { guardian, stopSec, replySec, plan, go, loading } = useApp()
  const set = (k: 'guardian' | 'stopSec' | 'replySec', v: string | number) => useApp.setState({ [k]: v } as any)
  const save = async () => { await plan(); go('preview') }
  return (
    <div className="screen">
      <div className="pad">
        <motion.h1 className="title" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}>Before your first walk</motion.h1>
        <div className="card">
          <p className="muted" style={{ fontSize: 13, color: 'var(--sw-muted)' }}>Meet the night shift: five agents that walk with you</p>
          <div className="crew" style={{ marginTop: 12 }}>
            {(['scout', 'watcher', 'rescuer', 'reporter', 'auditor'] as const).map((a, i) => (
              <motion.div key={a} className="m" initial={{ opacity: 0, scale: 0.6 }} animate={{ opacity: 1, scale: 1 }} transition={{ delay: 0.12 * i, type: 'spring', stiffness: 260, damping: 18 }}>
                <Avatar agent={a} size="lg" /><span>{AGENT_NAME[a].replace('Night ', '')}</span>
              </motion.div>
            ))}
          </div>
        </div>
        <div className="card row">
          <span className="avatar lg" style={{ background: 'rgba(232,151,90,0.2)', color: 'var(--sw-warn)', fontWeight: 700, fontFamily: 'var(--sw-font-display)', fontSize: 22 }}>{guardian[0]}</span>
          <div className="grow"><div className="label">Guardian</div><b style={{ fontSize: 17 }}>{guardian} Chen</b><div style={{ fontSize: 12, color: 'var(--sw-muted)' }}>Live link, verified phone</div></div>
          <select className="chip primary" aria-label="Change guardian" value={guardian} onChange={(e) => set('guardian', e.target.value)} style={{ background: 'transparent' }}>
            {['Maya', 'Dev', 'Sam'].map((g) => <option key={g}>{g}</option>)}
          </select>
        </div>
        <div className="card">
          <div className="label" style={{ marginBottom: 6 }}>Standing orders</div>
          <div className="orders">
            If I stop on a dim stretch for{' '}
            <select aria-label="Stop duration" value={stopSec} onChange={(e) => set('stopSec', +e.target.value)}>{[60, 90, 120].map((s) => <option key={s} value={s}>{s} s</option>)}</select>{' '}
            and don&rsquo;t answer in{' '}
            <select aria-label="Reply time" value={replySec} onChange={(e) => set('replySec', +e.target.value)}>{[30, 45, 60].map((s) => <option key={s} value={s}>{s} s</option>)}</select>, send{' '}
            <select className="who" aria-label="Guardian" value={guardian} onChange={(e) => set('guardian', e.target.value)}>{['Maya', 'Dev', 'Sam'].map((g) => <option key={g}>{g}</option>)}</select> my live location.
          </div>
        </div>
        <div className="card row" style={{ gap: 12 }}>
          <svg width="22" height="22" viewBox="0 0 24 24" aria-hidden="true" style={{ flex: '0 0 auto', color: 'var(--sw-muted)' }}><path d="M6.6 10.8a15 15 0 006.6 6.6l2.2-2.2a1 1 0 011-.25 11 11 0 003.5.56 1 1 0 011 1V20a1 1 0 01-1 1A17 17 0 013 4a1 1 0 011-1h3.5a1 1 0 011 1c0 1.2.2 2.4.56 3.5a1 1 0 01-.25 1z" fill="currentColor" /></svg>
          <div style={{ fontSize: 13 }}><b>Streetwise never calls 911 for you.</b><div style={{ color: 'var(--sw-muted)' }}>Mic is on only during a walk. Audio isn&rsquo;t stored.</div></div>
        </div>
        <div className="grow" />
        <button className="btn primary block" onClick={save} disabled={loading}>{loading ? 'Planning your route…' : 'Save · start walking'}</button>
      </div>
    </div>
  )
}
