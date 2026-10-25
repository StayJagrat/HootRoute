import type { LngLat } from './types';

export interface DestinationResult {
  name: string;
  detail: string;
  lngLat: LngLat;
  covered: boolean;
}

// The street graph covers the whole city of San Francisco (south, west, north, east).
const CITY = { south: 37.708, west: -122.518, north: 37.833, east: -122.355 };

export function inCity([lon, lat]: LngLat) {
  return lon >= CITY.west && lon <= CITY.east && lat >= CITY.south && lat <= CITY.north;
}

/** One search for the whole app: the gateway merges the offline map (places, landmarks, BART stations) with a geocoder
 *  (Geoapify, or Photon without a key) for real addresses, all limited to San Francisco. */
export async function searchPlaces(query: string, signal: AbortSignal): Promise<DestinationResult[]> {
  const q = query.trim();
  if (q.length < 2) return [];
  const r = await fetch(`/api/search?q=${encodeURIComponent(q)}&limit=8`, { signal });
  if (!r.ok) return [];
  const rows = (await r.json()) as { name: string; detail: string; lat: number; lon: number }[];
  return rows.map((x) => ({ name: x.name, detail: x.detail, lngLat: [x.lon, x.lat] as LngLat, covered: inCity([x.lon, x.lat]) }));
}

/** Name for a dropped pin from our own street graph ("Howard St between 3rd St and 4th St"). Works offline. */
export async function nameForPin([lon, lat]: LngLat): Promise<string> {
  try {
    const r = await fetch(`/api/where?lat=${lat}&lon=${lon}`, { signal: AbortSignal.timeout(3000) });
    if (r.ok) { const j = (await r.json()) as { text?: string }; if (j.text) return j.text; }
  } catch { /* gateway unreachable */ }
  return 'Dropped pin';
}

// ---------------------------------------------------------------- recent places (this device only)
const RECENT = 'hootroute:recent:v1';
export function recentPlaces(): DestinationResult[] {
  try { const v = JSON.parse(localStorage.getItem(RECENT) ?? '[]') as DestinationResult[]; return Array.isArray(v) ? v.slice(0, 5) : []; } catch { return []; }
}
export function rememberPlace(p: { name: string; lngLat: LngLat }) {
  try {
    const next = [{ name: p.name, detail: 'Recent', lngLat: p.lngLat, covered: true }, ...recentPlaces().filter((x) => x.name !== p.name)].slice(0, 5);
    localStorage.setItem(RECENT, JSON.stringify(next));
  } catch { /* storage blocked */ }
}
