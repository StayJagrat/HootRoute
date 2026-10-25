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

interface DemoSpot extends DestinationResult {
  /** OSM street name, so the city-wide street midpoint from /api/search can be dropped in favour of this pin. */
  street?: string;
}

/**
 * Demo spots pinned where data/cache/hours_evidence.json has checked hours (downtown / Union Square).
 * The API pins a street at the middle of its whole length, which for Geary or Market lands far from any cached hours.
 */
export const DEMO_SPOTS: DemoSpot[] = [
  { name: 'Moscone Center', detail: 'SoMa · stage demo start', lngLat: [-122.4016, 37.7842], covered: true },
  { name: 'City Hall', detail: 'Civic Center · stage demo end', lngLat: [-122.4193, 37.7793], covered: true },
  { name: '562 Sutter St', detail: 'Union Square · 32 places with checked hours', lngLat: [-122.40974, 37.78921], covered: true, street: 'Sutter Street' },
  { name: '798 Bush St', detail: 'Nob Hill · 26 places with checked hours', lngLat: [-122.41032, 37.79008], covered: true, street: 'Bush Street' },
  { name: '312 Kearny St', detail: 'Financial District · 23 places with checked hours', lngLat: [-122.40398, 37.79104], covered: true, street: 'Kearny Street' },
  { name: '555 Geary St', detail: 'Tenderloin · 22 places with checked hours', lngLat: [-122.4124, 37.78673], covered: true, street: 'Geary Street' },
  { name: "336 O'Farrell St", detail: "Union Square · 22 places with checked hours", lngLat: [-122.41043, 37.78626], covered: true, street: "O'Farrell Street" },
  { name: '599 Post St', detail: 'Union Square · 20 places with checked hours', lngLat: [-122.41155, 37.78779], covered: true, street: 'Post Street' },
  { name: '685 Market St', detail: 'Downtown · 14 places with checked hours', lngLat: [-122.40284, 37.78787], covered: true, street: 'Market Street' },
  { name: '601 Grant Ave', detail: 'Chinatown · 12 places with checked hours', lngLat: [-122.40609, 37.79259], covered: true, street: 'Grant Avenue' },
  { name: '299 Ellis St', detail: 'Tenderloin · 12 places with checked hours', lngLat: [-122.411, 37.78499], covered: true, street: 'Ellis Street' },
  { name: '450 Powell St', detail: 'Union Square · 8 places with checked hours', lngLat: [-122.40831, 37.78896], covered: true, street: 'Powell Street' },
];

function demoMatches(q: string): DemoSpot[] {
  const low = q.toLowerCase();
  return DEMO_SPOTS.filter((d) => d.name.toLowerCase().includes(low) || d.street?.toLowerCase().includes(low) || d.detail.toLowerCase().includes(low));
}

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
  const demo = demoMatches(q);
  const pinned = new Set(demo.flatMap((d) => (d.street ? [d.street.toLowerCase()] : [])));
  const seen = new Set<string>();
  return [...demo, ...a.filter((d) => !(d.detail === 'Street' && pinned.has(d.name.toLowerCase()))), ...b].filter((d) => {
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
