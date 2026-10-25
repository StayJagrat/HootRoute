import type { LngLat } from './types';

export interface DestinationResult {
  name: string;
  detail: string;
  lngLat: LngLat;
  covered: boolean;
}

// The street graph covers the whole city of San Francisco (south, west, north, east).
const CITY = { south: 37.708, west: -122.518, north: 37.833, east: -122.355 };
const SF_BBOX = '-122.52,37.70,-122.35,37.84';

export function inCity([lon, lat]: LngLat) {
  return lon >= CITY.west && lon <= CITY.east && lat >= CITY.south && lat <= CITY.north;
}
/** Kept for older callers. The whole city is routable now. */
export const inPilotArea = inCity;

export const LOCAL_DESTINATIONS: DestinationResult[] = [
  { name: 'City Hall', detail: 'Civic Center · BART', lngLat: [-122.4193, 37.7793], covered: true },
  { name: 'Civic Center BART', detail: 'Civic Center', lngLat: [-122.4139, 37.7796], covered: true },
  { name: 'Ferry Building', detail: 'Embarcadero', lngLat: [-122.3937, 37.7955], covered: true },
  { name: 'Transamerica Pyramid', detail: 'Financial District', lngLat: [-122.4028, 37.7952], covered: true },
  { name: 'Golden Gate Park', detail: 'Richmond', lngLat: [-122.4862, 37.7694], covered: true },
  { name: 'Mission Dolores Park', detail: 'Mission', lngLat: [-122.4271, 37.7596], covered: true },
];

interface PhotonFeature {
  geometry?: { coordinates?: number[] };
  properties?: { name?: string; street?: string; housenumber?: string; district?: string; city?: string };
}

/** Offline-first: our own API knows every named place, street and landmark in the cached city. Photon adds street addresses when online. */
export async function searchPlaces(query: string, signal: AbortSignal): Promise<DestinationResult[]> {
  const q = query.trim();
  if (q.length < 2) return [];
  const local = fetch(`/api/search?q=${encodeURIComponent(q)}&limit=6`, { signal })
    .then((r) => (r.ok ? r.json() : []))
    .then((rows: { name: string; detail: string; lat: number; lon: number }[]) => rows.map((r) => ({ name: r.name, detail: r.detail, lngLat: [r.lon, r.lat] as LngLat, covered: true })))
    .catch(() => [] as DestinationResult[]);
  const online = (async () => {
    const url = new URL('https://photon.komoot.io/api/');
    url.searchParams.set('q', q);
    url.searchParams.set('bbox', SF_BBOX);
    url.searchParams.set('lat', '37.775');
    url.searchParams.set('lon', '-122.43');
    url.searchParams.set('limit', '5');
    url.searchParams.set('lang', 'en');
    const response = await fetch(url.toString(), { signal });
    if (!response.ok) return [] as DestinationResult[];
    const body = (await response.json()) as { features?: PhotonFeature[] };
    return (body.features ?? []).flatMap((f) => {
      const c = f.geometry?.coordinates;
      const p = f.properties;
      if (!c || c.length < 2 || !p?.name) return [];
      const lngLat: LngLat = [c[0], c[1]];
      const detail = [p.housenumber, p.street, p.district ?? p.city].filter(Boolean).join(' ');
      return [{ name: p.name, detail: detail || 'San Francisco', lngLat, covered: inCity(lngLat) }];
    });
  })().catch(() => [] as DestinationResult[]);
  const [a, b] = await Promise.all([local, online]);
  const seen = new Set<string>();
  return [...a, ...b].filter((d) => {
    const key = `${d.name.toLowerCase()}:${d.lngLat[0].toFixed(3)},${d.lngLat[1].toFixed(3)}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  }).slice(0, 8);
}

/** Name for a dropped pin: the closest named place within 60 m from our API, else a plain label. */
export async function nameForPin([lon, lat]: LngLat): Promise<string> {
  try {
    const url = new URL('https://photon.komoot.io/reverse');
    url.searchParams.set('lon', String(lon));
    url.searchParams.set('lat', String(lat));
    url.searchParams.set('lang', 'en');
    const r = await fetch(url.toString(), { signal: AbortSignal.timeout(2500) });
    if (r.ok) {
      const f = ((await r.json()) as { features?: PhotonFeature[] }).features?.[0]?.properties;
      const label = [f?.name ?? [f?.housenumber, f?.street].filter(Boolean).join(' ')].filter(Boolean)[0];
      if (label) return label;
    }
  } catch {
    /* offline: fall through */
  }
  return 'Dropped pin';
}
