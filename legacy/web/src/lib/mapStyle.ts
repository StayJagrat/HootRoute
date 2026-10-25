import { layers, namedFlavor } from '@protomaps/basemaps'
import type { StyleSpecification } from 'maplibre-gl'

// Basemap styles built from the Figma palette. The tiles are a San Francisco extract in public/tiles/sf.pmtiles
// (see scripts/fetch_tiles.sh) and the labels use local font files in public/fonts, so the map works offline.
const night = {
  ...namedFlavor('dark'),
  background: '#10172a', earth: '#131a29', park_a: '#14241f', park_b: '#14241f', wood_a: '#13221e', wood_b: '#13221e', scrub_a: '#13221e', scrub_b: '#13221e',
  water: '#0c1730', pier: '#1a2338', buildings: '#1b2336', industrial: '#141b2b', school: '#161d2f', hospital: '#1c2036', pedestrian: '#1a2338',
  minor_a: '#262f48', minor_b: '#262f48', minor_service: '#202840', link: '#2c3654', major: '#2f3a5c', highway: '#3a4670', other: '#222b43',
  minor_casing: '#10172a', major_casing_early: '#10172a', major_casing_late: '#10172a', highway_casing_early: '#10172a', highway_casing_late: '#10172a', link_casing: '#10172a',
  railway: '#2a3350', boundaries: '#2a3350', roads_label_minor: '#8b95a8', roads_label_major: '#aeb6c8', roads_label_minor_halo: '#10172a', roads_label_major_halo: '#10172a',
  subplace_label: '#8b95a8', subplace_label_halo: '#10172a', city_label: '#aeb6c8', city_label_halo: '#10172a', ocean_label: '#4a5778', state_label: '#4a5778',
}
const day = {
  ...namedFlavor('light'),
  background: '#ece6d8', earth: '#f4f1ea', water: '#cddbe8', park_a: '#dfe8d4', park_b: '#dfe8d4', buildings: '#e5dfd1', pier: '#e8e2d4',
  minor_a: '#ffffff', minor_b: '#ffffff', minor_service: '#fbf9f4', major: '#ffffff', highway: '#f7e9c8', other: '#fbf9f4',
}

export function styleFor(mode: 'night' | 'day'): StyleSpecification {
  const flavor = mode === 'night' ? night : day
  const base = layers('protomaps', flavor as any, { lang: 'en' }).filter((l: any) => !l.layout?.['icon-image'])      // no sprite sheet offline: drop icon layers
  const flat = base.map((l: any) => (l.id === 'buildings' ? { ...l, maxzoom: 14.6 } : l))
  const solid = mode === 'night' ? '#1e2740' : '#e0d9c8'
  const b3d = { id: 'buildings-3d', type: 'fill-extrusion', source: 'protomaps', 'source-layer': 'buildings', minzoom: 14.6,
    paint: { 'fill-extrusion-color': solid, 'fill-extrusion-height': ['coalesce', ['get', 'height'], 9], 'fill-extrusion-base': ['coalesce', ['get', 'min_height'], 0], 'fill-extrusion-opacity': 0.92 } }
  const idx = flat.findIndex((l: any) => l.id === 'roads_label_minor')
  const ordered = [...flat.slice(0, idx < 0 ? flat.length : idx), b3d, ...flat.slice(idx < 0 ? flat.length : idx)]
  return {
    version: 8, glyphs: '/fonts/{fontstack}/{range}.pbf',
    sources: { protomaps: { type: 'vector', url: `pmtiles://${location.origin}/tiles/sf.pmtiles`, attribution: '© OpenStreetMap contributors · Protomaps' } },
    layers: ordered as any,
  }
}
