import MapBoundary from './MapBoundary';
import { useEffect, useRef } from 'react';
import maplibregl, { type LngLatBoundsLike, type Map as MLMap } from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import { buildStyle, UI_COLORS } from '../lib/mapStyle';
import { ensurePmtiles } from './MapView';
import type { LngLat } from '../lib/types';

interface Props {
  from: LngLat | null;
  to: LngLat | null;
  fast?: LngLat[] | null;
  best?: LngLat[] | null;
  highlight?: 'fast' | 'best';
  bottomPad: number;
  onTap: (p: LngLat) => void;
}

const empty = (): GeoJSON.FeatureCollection => ({ type: 'FeatureCollection', features: [] });
const line = (c?: LngLat[] | null): GeoJSON.FeatureCollection =>
  c && c.length > 1 ? { type: 'FeatureCollection', features: [{ type: 'Feature', properties: {}, geometry: { type: 'LineString', coordinates: c } }] } : empty();

function pin(kind: 'from' | 'to') {
  const el = document.createElement('div');
  el.className = kind === 'from' ? 'plan-pin plan-pin--from' : 'plan-pin plan-pin--to';
  return el;
}

/** Interactive city map for choosing a start and a destination. Tap anywhere in San Francisco to drop the active pin. */
export default function PickerMap(p: Props) {
  return <MapBoundary className="plan-map"><PickerMapInner {...p} /></MapBoundary>;
}

function PickerMapInner(p: Props) {
  const el = useRef<HTMLDivElement>(null);
  const map = useRef<MLMap | null>(null);
  const ready = useRef(false);
  const pins = useRef<{ from?: maplibregl.Marker; to?: maplibregl.Marker }>({});
  const tap = useRef(p.onTap);
  tap.current = p.onTap;
  const colors = UI_COLORS.night;

  useEffect(() => {
    if (!el.current) return;
    ensurePmtiles();
    const m = new maplibregl.Map({
      container: el.current,
      style: buildStyle('night'),
      center: [-122.432, 37.768],
      zoom: 11.7,
      maxBounds: [[-122.62, 37.64], [-122.28, 37.9]],
      attributionControl: { compact: true },
      pitchWithRotate: false,
      dragRotate: false,
    });
    m.on('load', () => {
      m.addSource('fast', { type: 'geojson', data: empty() });
      m.addSource('best', { type: 'geojson', data: empty() });
      m.addLayer({ id: 'fast', type: 'line', source: 'fast', layout: { 'line-cap': 'round', 'line-join': 'round' }, paint: { 'line-color': colors.text2, 'line-width': 4, 'line-opacity': 0.9, 'line-dasharray': [0.1, 2.2] } });
      m.addLayer({ id: 'best-casing', type: 'line', source: 'best', layout: { 'line-cap': 'round', 'line-join': 'round' }, paint: { 'line-color': colors.bg, 'line-width': 12 } });
      m.addLayer({ id: 'best', type: 'line', source: 'best', layout: { 'line-cap': 'round', 'line-join': 'round' }, paint: { 'line-color': colors.route, 'line-width': 6 } });
      ready.current = true;
      m.fire('plan-ready');
    });
    m.on('click', (ev) => tap.current([ev.lngLat.lng, ev.lngLat.lat]));
    map.current = m;
    return () => {
      m.remove();
      map.current = null;
      ready.current = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // pins
  useEffect(() => {
    const m = map.current;
    if (!m) return;
    (['from', 'to'] as const).forEach((k) => {
      const at = k === 'from' ? p.from : p.to;
      const cur = pins.current[k];
      if (!at) { cur?.remove(); pins.current[k] = undefined; return; }
      if (cur) cur.setLngLat(at);
      else pins.current[k] = new maplibregl.Marker({ element: pin(k), anchor: k === 'from' ? 'center' : 'bottom' }).setLngLat(at).addTo(m);
    });
  }, [p.from, p.to]);

  // routes + framing
  useEffect(() => {
    const m = map.current;
    if (!m) return;
    const apply = () => {
      (m.getSource('fast') as maplibregl.GeoJSONSource | undefined)?.setData(line(p.fast));
      (m.getSource('best') as maplibregl.GeoJSONSource | undefined)?.setData(line(p.best));
      if (m.getLayer('best')) {
        m.setPaintProperty('best', 'line-opacity', p.highlight === 'fast' ? 0.35 : 1);
        m.setPaintProperty('fast', 'line-width', p.highlight === 'fast' ? 6 : 4);
      }
      const pts: LngLat[] = [...(p.best ?? []), ...(p.fast ?? [])];
      if (!pts.length) pts.push(...([p.from, p.to].filter(Boolean) as LngLat[]));
      if (!pts.length) return;
      const lons = pts.map((c) => c[0]);
      const lats = pts.map((c) => c[1]);
      const b: LngLatBoundsLike = [[Math.min(...lons), Math.min(...lats)], [Math.max(...lons), Math.max(...lats)]];
      if (pts.length === 1) m.easeTo({ center: pts[0], zoom: 15, padding: { top: 60, bottom: p.bottomPad, left: 20, right: 20 }, duration: 600 });
      else m.fitBounds(b, { padding: { top: 70, bottom: p.bottomPad, left: 40, right: 40 }, maxZoom: 16, duration: 800 });
    };
    if (ready.current) apply();
    else m.once('plan-ready' as never, apply);
  }, [p.from, p.to, p.fast, p.best, p.highlight, p.bottomPad]);

  return <div ref={el} className="plan-map" />;
}
