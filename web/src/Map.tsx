import maplibregl, { type GeoJSONSource, type StyleSpecification } from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import { useEffect, useRef, useState } from 'react';
import { bounds, cumulative, sliceTo } from './lib/geo';
import type { LngLat } from './lib/types';

export interface MapRoute { id: string; coords: LngLat[]; active: boolean; dashed?: boolean }
export interface MapPlace { id: string; lngLat: LngLat; state: 'open' | 'unknown' | 'closed' }

const SF: LngLat = [-122.4194, 37.7749];
const KEY = (import.meta.env.VITE_GEOAPIFY_KEY as string | undefined) || '';
const STYLE_URL = KEY
  ? `https://maps.geoapify.com/v1/styles/dark-matter-dark-grey/style.json?apiKey=${encodeURIComponent(KEY)}`
  : 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json';
/** When the basemap can't load (offline venue Wi-Fi), routes still draw on plain ink. */
const BLANK: StyleSpecification = { version: 8, sources: {}, layers: [{ id: 'bg', type: 'background', paint: { 'background-color': '#06080c' } }] };
let styleCache: Promise<StyleSpecification> | null = null;
function loadStyle(): Promise<StyleSpecification> {
  styleCache ??= fetch(STYLE_URL, { signal: AbortSignal.timeout(6000) })
    .then((r) => { if (!r.ok) throw new Error(String(r.status)); return r.json() as Promise<StyleSpecification>; })
    .catch(() => { styleCache = null; return BLANK; });
  return styleCache;
}

const fc = (features: GeoJSON.Feature[]): GeoJSON.FeatureCollection => ({ type: 'FeatureCollection', features });
const line = (c: LngLat[], props: Record<string, unknown> = {}): GeoJSON.Feature => ({ type: 'Feature', properties: props, geometry: { type: 'LineString', coordinates: c } });
/** A ground circle as a 64-gon (metres, small-area approximation). */
const circle = ([lon, lat]: LngLat, r: number): GeoJSON.Feature => {
  const dLat = r / 111_320, dLon = r / (111_320 * Math.cos((lat * Math.PI) / 180));
  const ring = Array.from({ length: 65 }, (_, i) => { const a = (i / 64) * 2 * Math.PI; return [lon + dLon * Math.cos(a), lat + dLat * Math.sin(a)]; });
  return { type: 'Feature', properties: {}, geometry: { type: 'Polygon', coordinates: [ring] } };
};
const MOON = '#a9c1ff';
const GLOW = 'rgba(169,193,255,0.22)';
const CLEAR = 'rgba(0,0,0,0)';
const reduced = () => typeof matchMedia !== 'undefined' && matchMedia('(prefers-reduced-motion: reduce)').matches;
const flat = (c: string) => ['interpolate', ['linear'], ['line-progress'], 0, c, 1, c];

/** Night basemap with 3D buildings, the active route drawn in, a light pulse travelling along it, and alternatives. */
export function MapCanvas(p: {
  routes: MapRoute[];
  places?: MapPlace[];
  /** [lon, lat, 0..1] street-condition points, drawn as a heat layer under the routes */
  heat?: [number, number, number][];
  /** the area the dashboard describes, drawn as a faint ring */
  ring?: { center: LngLat; radius: number } | null;
  start?: LngLat | null;
  end?: LngLat | null;
  puck?: LngLat | null;
  progressM?: number;
  fitKey?: string;
  pad?: { left: number; bottom: number };
  onTap?: (ll: LngLat) => void;
  follow?: boolean;
  cinematic?: boolean;
  interactive?: boolean;
}) {
  const el = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const markers = useRef<Record<string, maplibregl.Marker>>({});
  const tap = useRef(p.onTap); tap.current = p.onTap;
  const anim = useRef<{ raf: number; reveal: number; t0: number }>({ raf: 0, reveal: 1, t0: 0 });
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let dead = false;
    void loadStyle().then((style) => {
      if (dead || !el.current) return;
      const m = new maplibregl.Map({
        container: el.current, style, center: SF, zoom: p.cinematic ? 13.4 : 12.6, pitch: p.cinematic ? 58 : 40, bearing: p.cinematic ? -18 : 0,
        attributionControl: { compact: true }, interactive: p.interactive !== false, maxPitch: 70,
      });
      m.on('click', (e) => tap.current?.([e.lngLat.lng, e.lngLat.lat]));
      m.on('load', () => {
        // 3D buildings from whichever vector source the basemap uses for buildings
        const b = (m.getStyle().layers ?? []).find((l) => 'source-layer' in l && l['source-layer'] === 'building') as { source?: string } | undefined;
        if (b?.source) {
          m.addLayer({ id: 'hr-3d', type: 'fill-extrusion', source: b.source, 'source-layer': 'building', minzoom: 13.5,
            paint: { 'fill-extrusion-color': ['interpolate', ['linear'], ['zoom'], 14, '#10151f', 17, '#18202e'],
              'fill-extrusion-height': ['coalesce', ['get', 'render_height'], ['get', 'height'], 12],
              'fill-extrusion-base': ['coalesce', ['get', 'render_min_height'], ['get', 'min_height'], 0],
              'fill-extrusion-opacity': 0.88 } });
        }
        // street conditions: one hue, ink -> moonlight, under everything route-coloured
        m.addSource('heat', { type: 'geojson', data: fc([]) });
        m.addSource('ring', { type: 'geojson', data: fc([]) });
        m.addLayer({ id: 'heat', type: 'heatmap', source: 'heat', maxzoom: 18,
          paint: { 'heatmap-weight': ['get', 'w'],
            'heatmap-intensity': ['interpolate', ['linear'], ['zoom'], 13, 0.35, 16, 0.9],
            'heatmap-radius': ['interpolate', ['linear'], ['zoom'], 13, 8, 15, 18, 17, 34],
            'heatmap-opacity': ['interpolate', ['linear'], ['zoom'], 13, 0.75, 17.5, 0.45],
            'heatmap-color': ['interpolate', ['linear'], ['heatmap-density'],
              0, 'rgba(126,157,255,0)', 0.15, 'rgba(56,72,140,0.35)', 0.4, 'rgba(90,118,214,0.55)', 0.7, 'rgba(140,168,255,0.72)', 1, 'rgba(214,226,255,0.85)'] } });
        m.addLayer({ id: 'ring-fill', type: 'fill', source: 'ring', paint: { 'fill-color': '#a9c1ff', 'fill-opacity': 0.03 } });
        m.addLayer({ id: 'ring', type: 'line', source: 'ring', paint: { 'line-color': '#a9c1ff', 'line-opacity': 0.45, 'line-width': 1.2, 'line-dasharray': [2, 3] } });
        m.addSource('alts', { type: 'geojson', data: fc([]) });
        m.addSource('active', { type: 'geojson', data: fc([]), lineMetrics: true });
        m.addSource('walked', { type: 'geojson', data: fc([]) });
        m.addSource('places', { type: 'geojson', data: fc([]) });
        m.addLayer({ id: 'alt', type: 'line', source: 'alts', filter: ['!', ['get', 'dashed']], layout: { 'line-cap': 'round', 'line-join': 'round' },
          paint: { 'line-color': '#8a93a6', 'line-width': 3, 'line-opacity': 0.5 } });
        m.addLayer({ id: 'alt-dash', type: 'line', source: 'alts', filter: ['get', 'dashed'], layout: { 'line-join': 'round' },
          paint: { 'line-color': '#f3b75e', 'line-width': 3.5, 'line-opacity': 0.85, 'line-dasharray': [1.4, 1.4] } });
        m.addLayer({ id: 'glow', type: 'line', source: 'active', layout: { 'line-cap': 'round', 'line-join': 'round' },
          paint: { 'line-width': 18, 'line-blur': 8, 'line-gradient': flat(GLOW) as never } });
        m.addLayer({ id: 'active', type: 'line', source: 'active', layout: { 'line-cap': 'round', 'line-join': 'round' },
          paint: { 'line-width': 5, 'line-gradient': flat(MOON) as never } });
        m.addLayer({ id: 'pulse', type: 'line', source: 'active', layout: { 'line-cap': 'round', 'line-join': 'round' },
          paint: { 'line-width': 5, 'line-gradient': flat(CLEAR) as never } });
        m.addLayer({ id: 'walked', type: 'line', source: 'walked', layout: { 'line-cap': 'round' }, paint: { 'line-color': '#3a4356', 'line-width': 6 } });
        m.addLayer({ id: 'places-halo', type: 'circle', source: 'places', filter: ['==', ['get', 'state'], 'open'],
          paint: { 'circle-radius': ['interpolate', ['linear'], ['zoom'], 12, 6, 16, 14], 'circle-color': '#63e2b4', 'circle-opacity': 0.12, 'circle-blur': 0.6 } });
        m.addLayer({ id: 'places', type: 'circle', source: 'places',
          paint: { 'circle-radius': ['interpolate', ['linear'], ['zoom'], 12, 2.5, 16, 5.5],
            'circle-color': ['match', ['get', 'state'], 'open', '#63e2b4', 'unknown', '#06080c', '#4a5263'],
            'circle-stroke-width': ['match', ['get', 'state'], 'unknown', 1.6, 0], 'circle-stroke-color': '#f3b75e' } });
        setReady(true);
      });
      map.current = m;
    });
    return () => { dead = true; cancelAnimationFrame(anim.current.raf); map.current?.remove(); map.current = null; markers.current = {}; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // draw the route in, then let a light pulse travel along it; the landing page slowly orbits the city
  useEffect(() => {
    const m = map.current;
    if (!m || !ready) return;
    anim.current.reveal = reduced() ? 1 : 0; anim.current.t0 = performance.now();
    const tick = (now: number) => {
      const a = anim.current; const mm = map.current;
      if (!mm || !mm.getLayer('active')) return;
      if (a.reveal < 1) {
        a.reveal = Math.min(1, a.reveal + 0.02);
        const edge = Math.max(0.0001, Math.min(0.9999, a.reveal));
        mm.setPaintProperty('active', 'line-gradient', (a.reveal >= 1 ? flat(MOON) : ['step', ['line-progress'], MOON, edge, CLEAR]) as never);
        mm.setPaintProperty('glow', 'line-gradient', (a.reveal >= 1 ? flat(GLOW) : ['step', ['line-progress'], GLOW, edge, CLEAR]) as never);
      } else if (!reduced()) {
        const t = ((now - a.t0) / 3400) % 1; const lo = Math.max(0.0002, t - 0.06), hi = Math.min(0.9998, t + 0.06);
        if (hi > lo + 0.001 && t > lo && t < hi) mm.setPaintProperty('pulse', 'line-gradient',
          ['interpolate', ['linear'], ['line-progress'], 0, CLEAR, lo, CLEAR, t, 'rgba(255,255,255,0.9)', hi, CLEAR, 1, CLEAR] as never);
      }
      if (p.cinematic && !reduced()) mm.setBearing(mm.getBearing() + 0.03);
      a.raf = requestAnimationFrame(tick);
    };
    cancelAnimationFrame(anim.current.raf);
    anim.current.raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(anim.current.raf);
  }, [ready, p.fitKey, p.cinematic]);

  const active = p.routes.find((r) => r.active)?.coords ?? [];
  useEffect(() => {
    const m = map.current;
    if (!m || !ready || !m.getSource('active')) return;
    (m.getSource('alts') as GeoJSONSource).setData(fc(p.routes.filter((r) => !r.active && r.coords.length > 1).map((r) => line(r.coords, { dashed: !!r.dashed }))));
    (m.getSource('active') as GeoJSONSource).setData(fc(active.length > 1 ? [line(active)] : []));
    const done = p.progressM && active.length > 1 ? sliceTo(active, p.progressM, cumulative(active)) : [];
    (m.getSource('walked') as GeoJSONSource).setData(fc(done.length > 1 ? [line(done)] : []));
    (m.getSource('places') as GeoJSONSource).setData(fc((p.places ?? []).map((pl) => ({ type: 'Feature', properties: { state: pl.state }, geometry: { type: 'Point', coordinates: pl.lngLat } }))));
  }, [ready, p.routes, p.places, p.progressM, active]);

  useEffect(() => {
    const m = map.current;
    if (!m || !ready || !m.getSource('heat')) return;
    (m.getSource('heat') as GeoJSONSource).setData(fc((p.heat ?? []).map(([lon, lat, w]) => ({ type: 'Feature', properties: { w }, geometry: { type: 'Point', coordinates: [lon, lat] } }))));
    (m.getSource('ring') as GeoJSONSource).setData(fc(p.ring ? [circle(p.ring.center, p.ring.radius)] : []));
  }, [ready, p.heat, p.ring]);

  useEffect(() => {
    const m = map.current;
    if (!m || !ready) return;
    const want: Record<string, [LngLat | null | undefined, string]> = { start: [p.start, 'pin'], end: [p.end, 'pin pin--end'], puck: [p.puck, 'puck'] };
    for (const [k, [ll, cls]] of Object.entries(want)) {
      if (!ll) { markers.current[k]?.remove(); delete markers.current[k]; continue; }
      if (!markers.current[k]) { const d = document.createElement('div'); d.className = cls; markers.current[k] = new maplibregl.Marker({ element: d }).setLngLat(ll).addTo(m); }
      else markers.current[k].setLngLat(ll);
    }
  }, [ready, p.start, p.end, p.puck]);

  // frame the journey with a camera flight; follow the walker during a walk
  useEffect(() => {
    const m = map.current;
    if (!m || !ready) return;
    const lines = p.routes.map((r) => r.coords).filter((c) => c.length > 1);
    const h = m.getContainer().clientHeight, w = m.getContainer().clientWidth;
    const pad = { top: 70, right: 50, left: Math.min(w * 0.6, (p.pad?.left ?? 0) + 50), bottom: Math.min(h * 0.72, (p.pad?.bottom ?? 0) + 40) };
    if (lines.length) {
      const cam = m.cameraForBounds(bounds(lines), { padding: pad, maxZoom: 16.2 });
      if (cam) m.flyTo({ ...cam, pitch: p.cinematic ? 58 : 45, bearing: p.cinematic ? m.getBearing() : -12, duration: reduced() ? 0 : 1800, essential: true });
    } else if (p.start || p.end) m.flyTo({ center: (p.end ?? p.start)!, zoom: 14.8, pitch: 45, duration: 1200 });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, p.fitKey]);
  useEffect(() => {
    const m = map.current;
    if (m && ready && p.follow && p.puck) m.easeTo({ center: p.puck, zoom: Math.max(m.getZoom(), 16.4), pitch: 55, duration: 900 });
  }, [ready, p.follow, p.puck]);

  return <div className="map" aria-label="Map"><div ref={el} style={{ position: 'absolute', inset: 0 }} /></div>;
}
