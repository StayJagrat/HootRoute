import { useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import { api } from '../api/client'
import { Avatar } from '../components/Avatar'
import { DEMO } from '../state/store'

interface Shop { id: string; name: string; cat: string; hours: string | null; hours_source: string | null; declared_until: number | null; walks_nearby: number }
interface Result { affected: number; before: Record<string, number> | null; after: Record<string, number> | null }
const clock = (m: number) => { const h = Math.floor(m / 60) % 24; return `${h % 12 || 12}:${String(m % 60).padStart(2, '0')} ${h >= 12 ? 'PM' : 'AM'}` }

export function ShopPage({ id }: { id: string }) {
  const [shop, setShop] = useState<Shop | null>(null); const [until, setUntil] = useState(25 * 60); const [haven, setHaven] = useState(true); const [light, setLight] = useState(true)
  const [res, setRes] = useState<Result | null>(null); const [busy, setBusy] = useState(false); const [err, setErr] = useState('')
  useEffect(() => { api<Shop>(`/api/shop/${id}`).then(setShop).catch((e) => setErr(String(e))) }, [id])
  const declare = async () => { setBusy(true); try { const r = await api<Result>(`/api/shop/${id}/declare`, { method: 'POST', json: { session: 'demo', until_minute: until, day: DEMO.day, minute: DEMO.minute, safe_haven: haven, front_light: light } }); setRes(r); setShop((s) => (s ? { ...s, declared_until: until } : s)) } catch (e) { setErr(String(e)) } setBusy(false) }
  if (err && !shop) return <div className="stage"><div className="phone day"><div className="pad"><h1 className="title">Shop not found</h1></div></div></div>
  if (!shop) return <div className="stage"><div className="phone day"><div className="pad"><p>Loading…</p></div></div></div>
  const gain = res?.before && res.after ? Math.round(((res.after.fast ?? 0) - (res.before.fast ?? 0)) * 10) / 10 : null
  return (
    <div className="stage"><div className="phone day"><div className="screen">
      <div className="awning" />
      <div className="pad" style={{ paddingTop: 16 }}>
        <div><h1 className="title" style={{ fontSize: 34 }}>{shop.name}</h1><div style={{ color: 'var(--sw-day-muted)', fontSize: 14 }}>{shop.cat.replace(/_/g, ' ')} · listed hours: {shop.hours ?? 'none'}{shop.hours_source && shop.hours_source !== 'osm' ? ` (${shop.hours_source})` : ''}</div><span className="chip ok" style={{ marginTop: 8 }}>Simulated shop for the demo</span></div>
        <div className="card">
          <div className="row"><div className="grow"><b style={{ fontSize: 18 }}>Staying open late</b><div style={{ fontSize: 13, color: 'var(--sw-day-muted)' }}>Walkers nearby see you as an open place, and routes can pass your door.</div></div></div>
          <div className="row" style={{ marginTop: 12, justifyContent: 'space-between' }}>
            <span className="label">until</span>
            <div className="row"><button className="btn" style={{ minHeight: 40, padding: '0 14px' }} onClick={() => setUntil((u) => Math.max(23 * 60, u - 30))} aria-label="30 minutes earlier">−</button><b style={{ fontFamily: 'var(--sw-font-display)', fontSize: 26, minWidth: 110, textAlign: 'center' }}>{clock(until)}</b><button className="btn" style={{ minHeight: 40, padding: '0 14px' }} onClick={() => setUntil((u) => Math.min(28 * 60, u + 30))} aria-label="30 minutes later">+</button></div>
          </div>
        </div>
        <div className="card">
          {[{ k: 'Safe haven', d: 'Walkers can wait inside if they need to', v: haven, s: setHaven }, { k: 'Front light on', d: "Your light counts toward the block's score", v: light, s: setLight }].map((t) => (
            <div className="row" key={t.k} style={{ padding: '6px 0' }}><div className="grow"><b>{t.k}</b><div style={{ fontSize: 13, color: 'var(--sw-day-muted)' }}>{t.d}</div></div><button className="toggle" role="switch" aria-checked={t.v} aria-label={t.k} onClick={() => t.s(!t.v)} /></div>
          ))}
        </div>
        {res && (
          <motion.div className="card row" initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} style={{ background: '#1b2030', color: '#fff', borderColor: '#1b2030' }}>
            <Avatar agent="scout" />
            <div style={{ fontSize: 14 }}><b>Your block just got brighter{res.affected ? ` for ${res.affected} ${res.affected === 1 ? 'person' : 'people'} walking nearby` : ''}.</b><div style={{ opacity: 0.85 }}>Scout re-scored routes past your door{gain !== null ? `: fastest route ${res.before!.fast} → ${res.after!.fast} (${gain >= 0 ? '+' : ''}${gain})` : ''}.</div></div>
          </motion.div>
        )}
        <div className="grow" />
        <button className="btn primary block" onClick={declare} disabled={busy}>{busy ? 'Telling Scout…' : shop.declared_until ? `Update: open until ${clock(until)}` : `Stay open until ${clock(until)}`}</button>
      </div>
    </div></div></div>
  )
}
