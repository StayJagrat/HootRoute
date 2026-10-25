import type { TravelMode, TravelSettings } from './types';

export const TRAVEL_LABEL: Record<TravelMode, string> = { walk: 'Walking', cycle: 'Cycling', wheelchair: 'Wheelchair / step-free' };
const KEY = 'hootroute:travel:v1';

export function defaultTravel(mode: TravelMode): TravelSettings {
  return { mode, options: mode === 'cycle' ? { speedKmh: 15, preferCycleways: true, avoidRoughSurfaces: false }
    : mode === 'wheelchair' ? { speedKmh: 3, avoidRoughSurfaces: true, requireKnownAccess: false, maxInclinePct: 5 } : {} };
}

export function loadTravel(): TravelSettings {
  try {
    const value: unknown = JSON.parse(localStorage.getItem(KEY) ?? 'null');
    if (!value || typeof value !== 'object' || !('mode' in value) || !['walk', 'cycle', 'wheelchair'].includes(String(value.mode))) return defaultTravel('walk');
    const mode = value.mode as TravelMode;
    const options: Record<string, unknown> = 'options' in value && value.options && typeof value.options === 'object' ? value.options as Record<string, unknown> : {};
    const result = defaultTravel(mode);
    for (const key of ['preferCycleways', 'avoidRoughSurfaces', 'requireKnownAccess'] as const) {
      if (key in options && typeof options[key] === 'boolean') result.options[key] = options[key];
    }
    if ('speedKmh' in options && typeof options.speedKmh === 'number' && (mode === 'cycle' ? [10, 15, 20, 25] : [2, 3, 4, 5]).includes(options.speedKmh)) result.options.speedKmh = options.speedKmh;
    if ('maxInclinePct' in options && typeof options.maxInclinePct === 'number' && [3, 5, 8].includes(options.maxInclinePct)) result.options.maxInclinePct = options.maxInclinePct;
    return result;
  } catch { return defaultTravel('walk'); }
}

export function saveTravel(value: TravelSettings) {
  try { localStorage.setItem(KEY, JSON.stringify(value)); } catch { /* optional device preferences */ }
}
