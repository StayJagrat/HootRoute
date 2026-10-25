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
/** When the basemap can't load (offline venue Wi-Fi), the routes still draw on plain ink. */
const BLANK: StyleSpecification = { version: 8, sources: {}, layers: [{ id: 'bg', type: 'background', paint: { 'background-color': '#06080c' } }] };

async function loadStyle(): Promise<StyleSpecification | string> {
  try {
    const r = await fetch(STYLE_URL, { signal: AbortSignal.timeout(5000) });
    if (!r.ok) throw new Error(String(r.status));
    return (await r.json()) as StyleSpecification;
  } catch {
    return BLANK;
  }
}

const fc = (features: GeoJSON.Feature[]): GeoJSON.FeatureCollection => ({ type: 'FeatureCollection', features });
const line = (c: LngLat[], props: Record<string, unknown> = {}): GeoJSON.Feature => ({ type: 'Feature', properties: props, geometry: { type: 'LineString', coordinates: c } });

export function MapCanvas(p: {
  routes: MapRoute[];
  places?: MapPlace[];
  start?: LngLat | null;
  end?: LngLat | null;
  puck?: LngLat | null;
  progressM?: number;
  fitKey?: string;
  pad?: { left: number; bottom: number };
  onTap?: (ll: LngLat) => void;
  follow?: boolean;
}) {
  const el = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const markers = useRef<Record<string, maplibregl.Marker>>({});
  const tap = useRef(p.onTap); tap.current = p.onTap;
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let dead = false;
    void loadStyle().then((style) => {
      if (dead || !el.current) return;
      const m = new maplibregl.Map({ container: el.current, style, center: SF, zoom: 12.6, attributionControl: { compact: true }, pitchWithRotate: false, dragRotate: false });
      m.touchZoomRotate.disableRotation();
      m.on('click', (e) => tap.current?.([e.lngLat.lng, e.lngLat.lat]));
      m.on('load', () => {
        m.addSource('routes', { type: 'geojson', data: fc([]) });
        m.addSource('walked', { type: 'geojson', data: fc([]) });
        m.addSource('places', { type: 'geojson', data: fc([]) });
        m.addLayer({ id: 'alt', type: 'line', source: 'routes', filter: ['all', ['!', ['get', 'active']], ['!', ['get', 'dashed']]], layout: { 'line-cap': 'round', 'line-join': 'round' },
          paint: { 'line-color': '#7b8496', 'line-width': 3, 'line-opacity': 0.55 } });
        m.addLayer({ id: 'alt-dash', type: 'line', source: 'routes', filter: ['all', ['!', ['get', 'active']], ['get', 'dashed']], layout: { 'line-join': 'round' },
          paint: { 'line-color': '#f3b75e', 'line-width': 3, 'line-opacity': 0.8, 'line-dasharray': [1.5, 1.5] } });
        m.addLayer({ id: 'glow', type: 'line', source: 'routes', filter: ['get', 'active'], layout: { 'line-cap': 'round', 'line-join': 'round' },
          paint: { 'line-color': '#a9c1ff', 'line-width': 16, 'line-opacity': 0.16, 'line-blur': 6 } });
        m.addLayer({ id: 'active', type: 'line', source: 'routes', filter: ['get', 'active'], layout: { 'line-cap': 'round', 'line-join': 'round' },
          paint: { 'line-color': '#a9c1ff', 'line-width': 4.5 } });
        m.addLayer({ id: 'walked', type: 'line', source: 'walked', layout: { 'line-cap': 'round' }, paint: { 'line-color': '#3a4356', 'line-width': 5 } });
        m.addLayer({ id: 'places', type: 'circle', source: 'places',
          paint: { 'circle-radius': ['interpolate', ['linear'], ['zoom'], 12, 2.5, 16, 5.5],
            'circle-color': ['match', ['get', 'state'], 'open', '#63e2b4', 'unknown', '#06080c', '#4a5263'],
            'circle-stroke-width': ['match', ['get', 'state'], 'unknown', 1.5, 0], 'circle-stroke-color': '#f3b75e' } });
        setReady(true);
      });
      map.current = m;
    });
    return () => { dead = true; map.current?.remove(); map.current = null; markers.current = {}; };
  }, []);

  const active = p.routes.find((r) => r.active)?.coords ?? [];
  useEffect(() => {
    const m = map.current;
    if (!m || !ready || !m.getSource('routes')) return;
    (m.getSource('routes') as GeoJSONSource).setData(fc([...p.routes].sort((a, b) => Number(a.active) - Number(b.active)).map((r) => line(r.coords, { active: r.active, dashed: !!r.dashed }))));
    const cum = active.length > 1 ? cumulative(active) : [];
    const done = p.progressM && active.length > 1 ? sliceTo(active, p.progressM, cum) : [];
    (m.getSource('walked') as GeoJSONSource).setData(fc(done.length > 1 ? [line(done)] : []));
    (m.getSource('places') as GeoJSONSource).setData(fc((p.places ?? []).map((pl) => ({ type: 'Feature', properties: { state: pl.state }, geometry: { type: 'Point', coordinates: pl.lngLat } }))));
  }, [ready, p.routes, p.places, p.progressM, active]);

  // start / end / you-are-here markers
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

  // frame the journey when it changes; follow the walker during a walk
  useEffect(() => {
    const m = map.current;
    if (!m || !ready) return;
    const lines = p.routes.map((r) => r.coords).filter((c) => c.length > 1);
    const pad = { top: 80, right: 60, left: (p.pad?.left ?? 0) + 60, bottom: (p.pad?.bottom ?? 0) + 60 };
    if (lines.length) m.fitBounds(bounds(lines), { padding: pad, duration: 700, maxZoom: 16.5 });
    else if (p.start || p.end) m.easeTo({ center: (p.end ?? p.start)!, zoom: 14.5, duration: 600 });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, p.fitKey]);
  useEffect(() => {
    const m = map.current;
    if (m && ready && p.follow && p.puck) m.easeTo({ center: p.puck, zoom: Math.max(m.getZoom(), 16), duration: 800 });
  }, [ready, p.follow, p.puck]);

  return <div className="map" aria-label="Map"><div ref={el} style={{ position: 'absolute', inset: 0 }} /></div>;
}
