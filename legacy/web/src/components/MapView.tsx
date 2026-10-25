import { useEffect, useRef, useState } from 'react'
import maplibregl, { type GeoJSONSource, type Map } from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import { Protocol } from 'pmtiles'
import type { LL, Route } from '../api/types'
import { color } from '../design/tokens'
import { cumulative, slice } from '../lib/geo'
import { styleFor } from '../lib/mapStyle'

let protocolReady = false
function ensureProtocol() { if (!protocolReady) { maplibregl.addProtocol('pmtiles', new Protocol().tile); protocolReady = true } }

const empty = { type: 'FeatureCollection' as const, features: [] as any[] }
const line = (coords: LL[], props: Record<string, unknown> = {}) => ({ type: 'Feature' as const, properties: props, geometry: { type: 'LineString' as const, coordinates: coords } })
const pt = (c: LL, props: Record<string, unknown> = {}) => ({ type: 'Feature' as const, properties: props, geometry: { type: 'Point' as const, coordinates: c } })
type Pad = { top: number; bottom: number; left: number; right: number }

interface Props {
  mode?: 'night' | 'day'; routes: Route[]; selected: string; draw?: number
  walker?: LL | null; follow?: boolean; bearing?: number; pad?: Pad
  showShops?: boolean; highlight?: LL | null; onClickMap?: (ll: LL) => void; interactive?: boolean; markers?: { ll: LL; html: string; cls?: string }[]
}

export function MapView({ mode = 'night', routes, selected, draw = 1, walker, follow, bearing = 0, pad, showShops = true, highlight, onClickMap, interactive = true, markers = [] }: Props) {
  const el = useRef<HTMLDivElement>(null); const map = useRef<Map | null>(null); const ready = useRef(false); const mk = useRef<maplibregl.Marker[]>([]); const fitted = useRef('')
  const [size, setSize] = useState(0)
  const onClick = useRef(onClickMap); onClick.current = onClickMap
  // smoothing state: the parent hands us targets a few times a second, we glide to them every frame
  const tgt = useRef({ ll: null as LL | null, bearing: 0, follow: false, pad: undefined as Pad | undefined }); const cur = useRef({ ll: null as LL | null, bearing: 0 })
  tgt.current = { ll: walker ?? null, bearing, follow: !!follow, pad }

  useEffect(() => {
    ensureProtocol()
    const m = new maplibregl.Map({ container: el.current!, style: styleFor(mode), center: [-122.4075, 37.7885], zoom: 14.6, pitch: mode === 'night' ? 42 : 0, bearing: mode === 'night' ? -14 : 0, attributionControl: false, interactive, fadeDuration: 120, maxPitch: 70 })
    map.current = m
    const ro = new ResizeObserver(() => { m.resize(); setSize(el.current ? el.current.clientWidth * 10000 + el.current.clientHeight : 0) }); ro.observe(el.current!)
    m.on('load', () => {
      for (const id of ['routes', 'gap', 'shops', 'walker', 'highlight']) m.addSource(id, { type: 'geojson', data: empty })
      const night = mode === 'night'
      m.addLayer({ id: 'fast-line', type: 'line', source: 'routes', filter: ['==', ['get', 'id'], 'fast'], layout: { 'line-cap': 'round', 'line-join': 'round' }, paint: { 'line-color': night ? '#d9dde8' : '#8a92a6', 'line-width': 3, 'line-dasharray': [0.1, 2.2], 'line-opacity': ['case', ['==', ['get', 'sel'], 1], 0.95, 0.5] } })
      m.addLayer({ id: 'best-glow', type: 'line', source: 'routes', filter: ['==', ['get', 'id'], 'best'], layout: { 'line-cap': 'round', 'line-join': 'round' }, paint: { 'line-color': color.primary, 'line-width': 14, 'line-blur': 10, 'line-opacity': ['case', ['==', ['get', 'sel'], 1], 0.55, 0.15] } })
      m.addLayer({ id: 'best-line', type: 'line', source: 'routes', filter: ['==', ['get', 'id'], 'best'], layout: { 'line-cap': 'round', 'line-join': 'round' }, paint: { 'line-color': color.primary, 'line-width': 5, 'line-opacity': ['case', ['==', ['get', 'sel'], 1], 1, 0.45] } })
      m.addLayer({ id: 'gap-line', type: 'line', source: 'gap', layout: { 'line-cap': 'round' }, paint: { 'line-color': color.danger, 'line-width': 7, 'line-opacity': 0.9 } })
      m.addLayer({ id: 'shop-halo', type: 'circle', source: 'shops', paint: { 'circle-radius': 12, 'circle-color': color.ok, 'circle-opacity': 0.18, 'circle-blur': 0.6, 'circle-pitch-alignment': 'map' } })
      m.addLayer({ id: 'shop-dot', type: 'circle', source: 'shops', paint: { 'circle-radius': 4.5, 'circle-color': color.ok, 'circle-stroke-width': 2, 'circle-stroke-color': night ? color.bg : '#fff', 'circle-pitch-alignment': 'map' } })
      m.addLayer({ id: 'hl', type: 'circle', source: 'highlight', paint: { 'circle-radius': 16, 'circle-color': color.warn, 'circle-opacity': 0.35, 'circle-stroke-width': 2, 'circle-stroke-color': color.warn } })
      m.addLayer({ id: 'walker-halo', type: 'circle', source: 'walker', paint: { 'circle-radius': 18, 'circle-color': color.primary, 'circle-opacity': 0.25, 'circle-pitch-alignment': 'map' } })
      m.addLayer({ id: 'walker-dot', type: 'circle', source: 'walker', paint: { 'circle-radius': 7, 'circle-color': '#fff', 'circle-stroke-width': 3, 'circle-stroke-color': color.primary, 'circle-pitch-alignment': 'map' } })
      ready.current = true; m.fire('swready' as any)
    })
    m.on('click', (e) => onClick.current?.([e.lngLat.lng, e.lngLat.lat]))

    // the glide loop: exponential smoothing of the walker position and heading, camera follows with jumpTo (no chained easings)
    let raf = 0, last = performance.now(), wasFollow = false
    const loop = (now: number) => {
      const dt = Math.min(0.1, (now - last) / 1000); last = now; const t = tgt.current, c = cur.current
      if (ready.current) {
        const src = m.getSource('walker') as GeoJSONSource | undefined
        if (t.ll) {
          if (!c.ll) { c.ll = [...t.ll] as LL; c.bearing = t.bearing }
          const k = 1 - Math.exp(-dt * 8), kb = 1 - Math.exp(-dt * 3.5)
          c.ll = [c.ll[0] + (t.ll[0] - c.ll[0]) * k, c.ll[1] + (t.ll[1] - c.ll[1]) * k]
          let db = ((t.bearing - c.bearing + 540) % 360) - 180; c.bearing += db * kb
          src?.setData({ type: 'FeatureCollection', features: [pt(c.ll)] })
          if (t.follow) { if (!wasFollow) { c.ll = [...t.ll] as LL; c.bearing = t.bearing }; m.jumpTo({ center: c.ll, bearing: c.bearing, pitch: 58, zoom: 17.2, padding: t.pad || { top: 220, bottom: 0, left: 0, right: 0 } }) }
          wasFollow = t.follow
        } else if (c.ll) { c.ll = null; src?.setData(empty); wasFollow = false }
      }
      raf = requestAnimationFrame(loop)
    }
    raf = requestAnimationFrame(loop)
    return () => { cancelAnimationFrame(raf); ro.disconnect(); mk.current.forEach((x) => x.remove()); m.remove(); map.current = null; ready.current = false }
  }, [mode])

  // route, gap and shop layers
  useEffect(() => {
    const m = map.current; if (!m) return
    const apply = () => {
      const feats: any[] = [], gaps: any[] = [], shops: any[] = []
      for (const r of routes) {
        const cum = cumulative(r.coords); const total = cum[cum.length - 1]; const upto = Math.max(0.001, draw) * total
        const sel = r.id === selected ? 1 : 0
        feats.push(line(slice(r.coords, cum, 0, upto), { id: r.id, sel }))
        if (r.gap.range && r.gap.m >= 60 && draw >= 1 && r.id === selected) gaps.push(line(slice(r.coords, cum, r.gap.range[0], Math.min(r.gap.range[1], total)), { id: r.id }))
        if (r.id === selected && showShops) for (const s of r.shops) shops.push(pt(s.ll, { name: s.name || s.cat }))
      }
      ;(m.getSource('routes') as GeoJSONSource)?.setData({ type: 'FeatureCollection', features: feats })
      ;(m.getSource('gap') as GeoJSONSource)?.setData({ type: 'FeatureCollection', features: gaps })
      ;(m.getSource('shops') as GeoJSONSource)?.setData({ type: 'FeatureCollection', features: draw >= 1 ? shops : [] })
    }
    if (ready.current) apply(); else m.once('swready' as any, apply)
  }, [routes, selected, draw, showShops, mode])

  useEffect(() => {
    const m = map.current; if (!m) return
    const apply = () => (m.getSource('highlight') as GeoJSONSource)?.setData(highlight ? { type: 'FeatureCollection', features: [pt(highlight)] } : empty)
    if (ready.current) apply(); else m.once('swready' as any, apply)
  }, [highlight, mode])

  // framing when not following the walker
  useEffect(() => {
    const m = map.current; if (!m || follow) return
    const r = routes.find((x) => x.id === selected) || routes[0]; if (!r) return
    const key = routes.map((x) => x.id + x.coords.length).join(',') + (pad ? JSON.stringify(pad) : '') + size
    if (fitted.current === key) return; fitted.current = key
    const b = new maplibregl.LngLatBounds(); routes.forEach((x) => x.coords.forEach((c) => b.extend(c as any)))
    m.fitBounds(b, { padding: pad || { top: 90, bottom: 330, left: 36, right: 36 }, pitch: mode === 'night' ? 36 : 0, bearing: mode === 'night' ? -10 : 0, duration: 1100, maxZoom: 16.4, easing: (t) => 1 - Math.pow(1 - t, 3) })
  }, [routes, selected, follow, mode, size])

  useEffect(() => {
    const m = map.current; if (!m) return
    mk.current.forEach((x) => x.remove()); mk.current = []
    for (const k of markers) { const d = document.createElement('div'); d.className = `mk ${k.cls || ''}`; d.innerHTML = k.html; mk.current.push(new maplibregl.Marker({ element: d, anchor: 'bottom' }).setLngLat(k.ll).addTo(m)) }
  }, [markers, mode])

  return <div ref={el} className="map" role="img" aria-label="Map of downtown San Francisco with the planned routes" />
}
