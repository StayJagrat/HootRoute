import { create } from 'zustand'
import { api, subscribe } from '../api/client'
import type { AgentEvent, Landmark, Meta, Route, RouteResponse, WalkState } from '../api/types'

export interface Pt { lat: number; lon: number; label: string }
export const DEMO = { day: 4, minute: 23 * 60 + 4, from: 'Powell St BART', to: 'Transamerica Pyramid' }   // Friday 11:04 PM

interface S {
  session: string; day: number; minute: number
  meta: Meta | null; landmarks: Landmark[]
  origin: Pt | null; dest: Pt | null
  resp: RouteResponse | null; selected: 'fast' | 'best'; loading: boolean; error: string | null
  events: AgentEvent[]
  screen: 'setup' | 'preview' | 'walk'
  guardian: string; walker: string; stopSec: number; replySec: number
  walk: (WalkState & { sim: { playing: boolean; stopped: boolean } }) | null
  init: () => Promise<void>
  setTime: (day: number, minute: number) => void
  plan: (o?: Pt, d?: Pt) => Promise<void>
  select: (id: 'fast' | 'best') => void
  go: (screen: S['screen']) => void
  startWalk: () => Promise<void>
  patchWalk: (p: Partial<NonNullable<S['walk']>>) => void
  reset: () => Promise<void>
}

let unsub: (() => void) | null = null
export const useApp = create<S>((set, get) => ({
  session: 'demo', day: DEMO.day, minute: DEMO.minute, meta: null, landmarks: [], origin: null, dest: null, resp: null, selected: 'best', loading: false, error: null,
  events: [], screen: 'setup', guardian: 'Maya', walker: 'Arya', stopSec: 90, replySec: 45, walk: null,

  async init() {
    const [meta, landmarks] = await Promise.all([api<Meta>('/api/meta'), api<Landmark[]>('/api/landmarks')])
    const from = landmarks.find((l) => l.name === DEMO.from), to = landmarks.find((l) => l.name === DEMO.to)
    set({ meta, landmarks, origin: from ? { lat: from.lat, lon: from.lon, label: from.name } : null, dest: to ? { lat: to.lat, lon: to.lon, label: to.name } : null })
    unsub?.(); unsub = subscribe(get().session, (e) => set((s) => ({ events: [...s.events.slice(-120), e] })))
  },
  setTime(day, minute) { set({ day, minute }) },
  async plan(o, d) {
    const s = get(); const origin = o || s.origin, dest = d || s.dest
    if (!origin || !dest) return
    set({ origin, dest, loading: true, error: null })
    try {
      const resp = await api<RouteResponse>('/api/route', { method: 'POST', json: { session: s.session, origin: { lat: origin.lat, lon: origin.lon }, dest: { lat: dest.lat, lon: dest.lon }, day: s.day, minute: s.minute } })
      set({ resp, selected: resp.routes.some((r) => r.id === 'best') ? 'best' : 'fast', loading: false })
    } catch (e) { set({ loading: false, error: String(e) }) }
  },
  select(id) { set({ selected: id }) },
  go(screen) { set({ screen }) },
  async startWalk() {
    const s = get(); if (!s.resp) return
    const route = s.resp.routes.find((r: Route) => r.id === s.selected) || s.resp.routes[0]
    const r = await api<{ id: string }>('/api/walk/start', { method: 'POST', json: { session: s.session, route_id: route.id, walker: s.walker, guardian: s.guardian } })
    const w = await api<WalkState>(`/api/walk/${r.id}`)
    set({ walk: { ...w, sim: { playing: true, stopped: false } }, screen: 'walk' })
  },
  patchWalk(p) { const w = get().walk; if (w) set({ walk: { ...w, ...p, sim: { ...w.sim, ...(p as any).sim } } }) },
  async reset() { await api('/api/session/reset', { method: 'POST', json: { session: get().session } }); set({ resp: null, events: [], walk: null, screen: 'setup' }); await get().plan() },
}))
export const selectedRoute = (s: S): Route | undefined => s.resp?.routes.find((r) => r.id === s.selected) || s.resp?.routes[0]
