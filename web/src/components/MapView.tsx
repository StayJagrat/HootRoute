import MapBoundary from './MapBoundary';
import { useEffect, useMemo, useRef, useState } from 'react';
import maplibregl, { type GeoJSONSource, type LngLatBoundsLike, type Map as MLMap, type PaddingOptions } from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import { Protocol } from 'pmtiles';
import { buildStyle, UI_COLORS, type Theme } from '../lib/mapStyle';
import { along, bounds, cumulative, lineLength, offsetPoint, project, sliceFrom, sliceTo } from '../lib/geo';
import { isListedOpen, openLabel } from '../lib/format';
import type { DemoData, LngLat, Place } from '../lib/types';
import { ICONS } from './icons';

export interface MapViewProps {
  theme: Theme;
  data: DemoData;
  choice?: 'hootroute' | 'usual';
  places: Place[];
  showShortest?: boolean;
  showLamps?: boolean;
  showDimLabel?: boolean;
  showSegments?: boolean; // control room: City pipeline scores, if /data/segments.geojson exists
  brightened?: string[]; // place ids whose block just got brighter
  puck?: { lngLat: LngLat; heading: number; variant?: 'normal' | 'checkin' | 'alert' } | null;
  progress?: number; // 0..1 of the active route already walked
  camera: 'follow' | 'overview' | 'fit' | 'spot';   // spot: flat, street-level context around the puck (alert screens)
  padding?: Partial<PaddingOptions>;
  interactive?: boolean;
  onStretchClick?: (id: string, at: { x: number; y: number }) => void;
  bouncePlace?: string | null;
  className?: string;
}

const fc = (features: GeoJSON.Feature[]): GeoJSON.FeatureCollection => ({ type: 'FeatureCollection', features });
const ls = (coords: LngLat[], props: Record<string, unknown> = {}): GeoJSON.Feature => ({ type: 'Feature', properties: props, geometry: { type: 'LineString', coordinates: coords } });
const pt = (c: LngLat, props: Record<string, unknown> = {}): GeoJSON.Feature => ({ type: 'Feature', properties: props, geometry: { type: 'Point', coordinates: c } });

let pmtilesReady = false;
export function ensurePmtiles() {
  if (pmtilesReady) return;
  maplibregl.addProtocol('pmtiles', new Protocol().tile);
  pmtilesReady = true;
}

/** Place and street names come from map data and user-chosen destinations; never let them become markup. */
const esc = (t: string) => t.replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c] as string);

export default function MapView(p: MapViewProps) {
  return <MapBoundary className={p.className}><MapViewInner {...p} /></MapBoundary>;
}

function MapViewInner(p: MapViewProps) {
  const el = useRef<HTMLDivElement>(null);
  const map = useRef<MLMap | null>(null);
  const [ready, setReady] = useState(false);
  const [sizeTick, setSizeTick] = useState(0);
  const markers = useRef<Record<string, maplibregl.Marker>>({});
  const puckMarker = useRef<maplibregl.Marker | null>(null);
  const colors = UI_COLORS[p.theme];
  const clickRef = useRef(p.onStretchClick);
  clickRef.current = p.onStretchClick;
  const line = p.choice === 'usual' ? p.data.shortest : p.data.route;
  const cum = useMemo(() => cumulative(line), [line]);
  const total = useMemo(() => lineLength(line), [line]);

  // lamp evidence dots along the active route (hollow = reported/observed out)
  const lamps = useMemo(() => {
    const out: GeoJSON.Feature[] = [];
    const dims = p.data.dimStretches.map((d) => {
      const a = project(line, d.line[0], cum);
      const b = project(line, d.line[d.line.length - 1], cum);
      return a.offset < 25 ? [Math.min(a.meters, b.meters) - 5, Math.max(a.meters, b.meters) + 5] : null;
    }).filter(Boolean) as [number, number][];
    for (let m = 18; m < total - 10; m += 34) {
      const a = along(line, m, cum);
      const inDim = dims.some(([s, e]) => m >= s && m <= e);
      out.push(pt(offsetPoint(a.lngLat, a.heading, 11), { broken: inDim }));
    }
    return fc(out);
  }, [line, cum, total, p.data.dimStretches]);

  // ---------------------------------------------------------------- init
  useEffect(() => {
    if (!el.current) return;
    ensurePmtiles();
    const b = bounds([p.data.route, p.data.shortest]);
    const m = new maplibregl.Map({
      container: el.current,
      style: buildStyle(p.theme),
      bounds: b as LngLatBoundsLike,
      fitBoundsOptions: { padding: 40 },
      attributionControl: { compact: true },
      interactive: p.interactive ?? true,
      pitchWithRotate: true,
      dragRotate: true,
      maxZoom: 19,
    });
    map.current = m;
    // Tile requests cancelled by camera moves are routine; anything else is worth a warning, never a crash.
    m.on('error', (e) => { if ((e.error as Error | undefined)?.name !== 'AbortError') console.warn('map:', (e.error as Error | undefined)?.message ?? e); });
    // 'style.load' (not 'load'): our overlays must draw even when the tile server
    // is unreachable — on a bad venue network the route, lamps and places still show.
    m.once('style.load', () => {
      if (m.getSource('shortest')) return;
      m.addSource('shortest', { type: 'geojson', data: fc([]) });
      m.addSource('route-ahead', { type: 'geojson', data: fc([]) });
      m.addSource('route-done', { type: 'geojson', data: fc([]) });
      m.addSource('dims', { type: 'geojson', data: fc([]) });
      m.addSource('lamps', { type: 'geojson', data: fc([]) });
      m.addSource('glow', { type: 'geojson', data: fc([]) });
      m.addSource('segments', { type: 'geojson', data: fc([]) });
      m.addLayer({ id: 'segments', type: 'line', source: 'segments', layout: { 'line-cap': 'round' }, paint: {
        'line-color': colors.text,
        'line-opacity': ['interpolate', ['linear'], ['coalesce', ['get', 'score'], 50], 0, 0.06, 100, 0.55],
        'line-width': ['interpolate', ['linear'], ['coalesce', ['get', 'score'], 50], 0, 1.5, 100, 6],
      } });
      m.addLayer({ id: 'glow', type: 'line', source: 'glow', layout: { 'line-cap': 'round' }, paint: { 'line-color': colors.open, 'line-width': 26, 'line-blur': 14, 'line-opacity': 0.55 } });
      m.addLayer({ id: 'shortest', type: 'line', source: 'shortest', layout: { 'line-cap': 'round', 'line-join': 'round' }, paint: { 'line-color': colors.text2, 'line-width': 4, 'line-dasharray': [0.1, 2.2] } });
      m.addLayer({ id: 'route-done', type: 'line', source: 'route-done', layout: { 'line-cap': 'round', 'line-join': 'round' }, paint: { 'line-color': colors.route, 'line-width': 6, 'line-opacity': 0.35 } });
      m.addLayer({ id: 'route-casing', type: 'line', source: 'route-ahead', layout: { 'line-cap': 'round', 'line-join': 'round' }, paint: { 'line-color': colors.bg, 'line-width': 13 } });
      m.addLayer({ id: 'route', type: 'line', source: 'route-ahead', layout: { 'line-cap': 'round', 'line-join': 'round' }, paint: { 'line-color': colors.route, 'line-width': 7 } });
      m.addLayer({ id: 'dims-erase', type: 'line', source: 'dims', filter: ['==', ['get', 'onActive'], true], paint: { 'line-color': colors.bg, 'line-width': 8 } });
      m.addLayer({ id: 'dims', type: 'line', source: 'dims', filter: ['==', ['get', 'onActive'], true], paint: { 'line-color': colors.route, 'line-width': 6, 'line-opacity': 0.6, 'line-dasharray': [1.2, 1] } });
      m.addLayer({ id: 'dims-hit', type: 'line', source: 'dims', paint: { 'line-color': '#000', 'line-opacity': 0, 'line-width': 28 } });
      m.addLayer({ id: 'lamps-halo', type: 'circle', source: 'lamps', filter: ['!', ['get', 'broken']], paint: { 'circle-radius': 7, 'circle-color': colors.text, 'circle-opacity': 0.1, 'circle-blur': 0.6 } });
      m.addLayer({ id: 'lamps', type: 'circle', source: 'lamps', paint: {
        'circle-radius': ['interpolate', ['linear'], ['zoom'], 14, 1.2, 18, 3.2],
        'circle-color': ['case', ['get', 'broken'], 'rgba(0,0,0,0)', colors.text],
        'circle-stroke-color': colors.text2,
        'circle-stroke-width': ['case', ['get', 'broken'], 1.4, 0],
        'circle-opacity': 0.9,
      } });
      m.addLayer({ id: 'dim-label', type: 'symbol', source: 'dims', filter: ['==', ['get', 'showLabel'], true], layout: {
        'symbol-placement': 'line-center', 'text-field': ['get', 'label'], 'text-font': ['Noto Sans Medium'], 'text-size': 11,
        'text-letter-spacing': 0.08, 'text-offset': [0, -1.4], 'text-keep-upright': true,
      }, paint: { 'text-color': colors.text2, 'text-halo-color': colors.surface, 'text-halo-width': 3 } });
      m.on('click', 'dims-hit', (ev) => {
        const id = ev.features?.[0]?.properties?.id as string | undefined;
        if (id && clickRef.current) clickRef.current(id, { x: ev.point.x, y: ev.point.y });
      });
      m.on('mouseenter', 'dims-hit', () => (m.getCanvas().style.cursor = 'pointer'));
      m.on('mouseleave', 'dims-hit', () => (m.getCanvas().style.cursor = ''));
      setReady(true);
    });
    // Maps inside animated overlays (guardian alert) start at the wrong size.
    let last = '';
    const ro = new ResizeObserver(() => {
      const r = el.current?.getBoundingClientRect();
      const key = r ? `${Math.round(r.width)}x${Math.round(r.height)}` : '';
      if (key === last) return;
      last = key;
      m.resize();
      setSizeTick((t) => t + 1);
    });
    ro.observe(el.current);
    return () => {
      ro.disconnect();
      m.remove();
      map.current = null;
      markers.current = {};
      puckMarker.current = null;
      setReady(false);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [p.theme]);

  // ---------------------------------------------------------------- data layers
  useEffect(() => {
    const m = map.current;
    if (!m || !ready || !m.getSource('route-ahead')) return;   // style reloading (theme switch, hot reload): sources come back with 'load'
    const walked = (p.progress ?? 0) * total;
    (m.getSource('route-ahead') as GeoJSONSource).setData(fc([ls(walked > 1 ? sliceFrom(line, walked, cum) : line)]));
    (m.getSource('route-done') as GeoJSONSource).setData(fc(walked > 1 ? [ls(sliceTo(line, walked, cum))] : []));
    (m.getSource('shortest') as GeoJSONSource).setData(fc(p.showShortest ? [ls(p.data.shortest)] : []));
    (m.getSource('lamps') as GeoJSONSource).setData(p.showLamps === false ? fc([]) : lamps);
    const active = p.choice === 'usual' ? 'usual' : 'hootroute';
    (m.getSource('dims') as GeoJSONSource).setData(fc(p.data.dimStretches.map((d) => {
      const onActive = active === 'hootroute' ? d.onRoute : !d.onRoute || project(p.data.shortest, d.line[0]).offset < 25;
      return ls(d.line, { id: d.id, onActive, showLabel: !!p.showDimLabel && (onActive || !!p.showShortest), label: `FEWER LIGHTS · ${d.meters} M` });
    })));
    // brightened block: route portion within ~110 m of the place
    const glow: GeoJSON.Feature[] = [];
    for (const id of p.brightened ?? []) {
      const pl = p.places.find((x) => x.id === id);
      if (!pl) continue;
      const pr = project(line, pl.lngLat, cum);
      if (pr.offset > 60) continue;
      const a = Math.max(0, pr.meters - 110);
      const b = Math.min(total, pr.meters + 110);
      glow.push(ls(sliceTo(sliceFrom(line, a, cum), b - a)));
    }
    (m.getSource('glow') as GeoJSONSource).setData(fc(glow));
  }, [ready, p.progress, p.showShortest, p.showLamps, p.showDimLabel, p.choice, p.brightened, p.places, line, cum, total, lamps, p.data]);

  // optional City-pipeline segments (control room)
  useEffect(() => {
    const m = map.current;
    if (!m || !ready || !p.showSegments) return;
    fetch('/data/segments.geojson')
      .then((r) => (r.ok ? r.json() : null))
      .then((gj) => gj && (m.getSource('segments') as GeoJSONSource | undefined)?.setData(gj))
      .catch(() => undefined);
  }, [ready, p.showSegments]);

  // ---------------------------------------------------------------- DOM markers
  useEffect(() => {
    const m = map.current;
    if (!m || !ready) return;
    const want = new Set<string>();
    const put = (key: string, lngLat: LngLat, html: string, anchor: maplibregl.PositionAnchor = 'left', offset: [number, number] = [-17, 0]) => {
      want.add(key);
      let mk = markers.current[key];
      if (!mk) {
        const div = document.createElement('div');
        mk = new maplibregl.Marker({ element: div, anchor, offset }).setLngLat(lngLat).addTo(m);
        markers.current[key] = mk;
      }
      const node = mk.getElement();
      if (node.innerHTML !== html) node.innerHTML = html;
      mk.setLngLat(lngLat);
    };
    put('start', p.data.start.lngLat, `<div class="end-pin"><span style="width:18px;height:18px;display:inline-flex">${ICONS.train}</span>${esc(p.data.start.name)}</div>`, 'bottom-left', [-14, -6]);
    put('end', p.data.end.lngLat, `<div class="end-pin"><span style="width:18px;height:18px;display:inline-flex">${ICONS.star}</span>${esc(p.data.end.name)}</div>`, 'top-left', [-14, 6]);
    for (const pl of p.places) {
      const closed = !isListedOpen(pl.openUntil);
      const cls = `place-marker${closed ? ' place-marker--closed' : ''}${p.bouncePlace === pl.id ? ' place-marker--bounce' : ''}`;
      put(`place:${pl.id}`, pl.lngLat,
        `<div class="${cls}" title="${esc(pl.name)}${pl.simulated ? ' (simulated)' : ''}"><div class="place-marker__pin" style="color:#0B0E14">${ICONS[pl.kind]}</div><div class="place-marker__tag">${pl.simulated ? '' : `${esc(pl.name)} · `}${openLabel(pl)}${pl.safeHaven && !closed ? `<span style="width:12px;height:12px;display:inline-flex">${ICONS.star}</span>` : ''}</div></div>`);
    }
    for (const k of Object.keys(markers.current)) if (!want.has(k)) {
      markers.current[k].remove();
      delete markers.current[k];
    }
  }, [ready, p.places, p.data, p.bouncePlace]);

  // puck
  useEffect(() => {
    const m = map.current;
    if (!m || !ready) return;
    if (!p.puck) {
      puckMarker.current?.remove();
      puckMarker.current = null;
      return;
    }
    if (!puckMarker.current) {
      const div = document.createElement('div');
      div.innerHTML = '<div class="puck"><div class="puck__halo"></div><div class="puck__cone"></div><div class="puck__dot"></div></div>';
      puckMarker.current = new maplibregl.Marker({ element: div, rotationAlignment: 'map', pitchAlignment: 'map' }).setLngLat(p.puck.lngLat).addTo(m);
    }
    const mk = puckMarker.current;
    mk.setLngLat(p.puck.lngLat);
    mk.setRotation(p.puck.heading);
    const inner = mk.getElement().firstElementChild as HTMLElement;
    inner.className = `puck${p.puck.variant === 'alert' ? ' puck--alert' : p.puck.variant === 'checkin' ? ' puck--checkin' : ''}`;
  }, [ready, p.puck]);

  // ---------------------------------------------------------------- camera
  const lastCam = useRef<string>('');
  useEffect(() => {
    const m = map.current;
    if (!m || !ready) return;
    const padding = { top: 40, bottom: 40, left: 40, right: 40, ...p.padding };
    if (p.camera === 'spot' && p.puck) {
      m.easeTo({ center: p.puck.lngLat, bearing: 0, pitch: 0, zoom: 15.6, duration: 0, essential: true });
    } else if (p.camera === 'follow' && p.puck) {
      m.easeTo({ center: p.puck.lngLat, bearing: p.puck.heading, pitch: 52, zoom: 17.4, padding, duration: 900, essential: true });
      lastCam.current = 'follow';
    } else {
      const key = `${p.camera}:${JSON.stringify(padding)}:${p.showShortest}:${sizeTick}`;
      if (lastCam.current === key) return;
      lastCam.current = key;
      const b = bounds(p.showShortest ? [p.data.route, p.data.shortest] : [line]);
      m.fitBounds(b as LngLatBoundsLike, { padding, pitch: 0, bearing: 0, duration: lastCam.current ? 800 : 0, maxZoom: 17 });
    }
  }, [ready, p.camera, p.puck, p.padding, p.showShortest, line, p.data, sizeTick]);

  return <div ref={el} className={p.className} style={{ position: 'absolute', inset: 0 }} />;
}
