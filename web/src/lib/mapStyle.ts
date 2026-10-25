import { layers, namedFlavor } from '@protomaps/basemaps';
import type { StyleSpecification } from 'maplibre-gl';

// Local SF PMTiles extract, recolored with Abhishek's Night/Day map palette.
// The font PBFs and tile archive are prepared by scripts/fetch_tiles.sh.
export type Theme = 'night' | 'day';

export const MAP_COLORS: Record<Theme, Record<string, string>> = {
  night: {
    land: '#141924', minor: '#232B3A', major: '#33405A', casing: '#141924', water: '#0E2233', park: '#172820',
    building: '#1A2030', buildingTop: '#202838', label: '#7F889A', halo: '#141924', path: '#2A3346',
  },
  day: {
    land: '#ECE6DA', minor: '#FFFFFF', major: '#FFFFFF', casing: '#DCD3C2', water: '#B9D8EC', park: '#CFE3C3',
    building: '#E3DCCE', buildingTop: '#E8E1D4', label: '#6E7380', halo: '#F4F0E8', path: '#F8F5EF',
  },
};

export const UI_COLORS: Record<Theme, Record<string, string>> = {
  night: { route: '#6B83FF', open: '#4FD1A5', checkin: '#FF8A3D', alert: '#EF4438', text: '#ECE7DC', text2: '#8E97A8', bg: '#10141C', surface: '#1B2230' },
  day: { route: '#4A63E8', open: '#1E9E74', checkin: '#E36A1A', alert: '#D92D20', text: '#151A22', text2: '#6A6F7B', bg: '#F4F0E8', surface: '#FFFFFF' },
};

export function buildStyle(theme: Theme): StyleSpecification {
  const c = MAP_COLORS[theme];
  const base = namedFlavor(theme === 'night' ? 'dark' : 'light');
  const flavor = {
    ...base,
    background: c.land, earth: c.land, water: c.water,
    park_a: c.park, park_b: c.park, wood_a: c.park, wood_b: c.park,
    scrub_a: c.park, scrub_b: c.park,
    pedestrian: c.path, other: c.path,
    buildings: c.building, industrial: c.building,
    minor_a: c.minor, minor_b: c.minor, minor_service: c.minor,
    link: c.major, major: c.major, highway: c.major,
    minor_casing: c.casing, major_casing_early: c.casing, major_casing_late: c.casing,
    link_casing: c.casing, highway_casing_early: c.casing, highway_casing_late: c.casing,
    roads_label_minor: c.label, roads_label_major: c.label,
    roads_label_minor_halo: c.halo, roads_label_major_halo: c.halo,
    subplace_label: c.label, subplace_label_halo: c.halo,
    city_label: c.label, city_label_halo: c.halo,
  };
  // Offline extract has no sprite atlas; skip layers that require icons.
  const baseLayers = layers('protomaps', flavor, { lang: 'en' })
    .filter((layer) => !('layout' in layer && layer.layout && 'icon-image' in layer.layout))
    .map((layer) => layer.id === 'buildings' ? { ...layer, maxzoom: 14.6 } : layer);
  const buildings3d = {
    id: 'buildings-3d', type: 'fill-extrusion', source: 'protomaps', 'source-layer': 'buildings', minzoom: 14.6,
    paint: {
      'fill-extrusion-color': c.buildingTop,
      'fill-extrusion-height': ['coalesce', ['get', 'height'], 9],
      'fill-extrusion-base': ['coalesce', ['get', 'min_height'], 0],
      'fill-extrusion-opacity': 0.85,
    },
  } as StyleSpecification['layers'][number];
  const firstLabel = baseLayers.findIndex((layer) => layer.id === 'roads_label_minor');
  const at = firstLabel < 0 ? baseLayers.length : firstLabel;
  return {
    version: 8,
    glyphs: '/fonts/{fontstack}/{range}.pbf',
    sources: {
      protomaps: {
        type: 'vector',
        url: `pmtiles://${location.origin}/tiles/sf.pmtiles`,
        attribution: '© OpenStreetMap contributors · Protomaps',
      },
    },
    layers: [...baseLayers.slice(0, at), buildings3d, ...baseLayers.slice(at)] as StyleSpecification['layers'],
  };
}
