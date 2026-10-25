import type { LngLat } from './types';

// A PWA can't track location or play audio with the phone locked,
// so a walk keeps the screen awake and the app in the foreground.

type WakeLockSentinelLike = { release: () => Promise<void> };
let sentinel: WakeLockSentinelLike | null = null;
let wanted = false;

async function acquire() {
  try {
    const nav = navigator as Navigator & { wakeLock?: { request: (t: 'screen') => Promise<WakeLockSentinelLike> } };
    if (nav.wakeLock && document.visibilityState === 'visible') sentinel = await nav.wakeLock.request('screen');
  } catch {
    sentinel = null;
  }
}

export async function keepAwake(on: boolean) {
  wanted = on;
  if (on) await acquire();
  else {
    await sentinel?.release().catch(() => undefined);
    sentinel = null;
  }
}

document.addEventListener('visibilitychange', () => {
  if (wanted && document.visibilityState === 'visible') void acquire();
});

export const hasWakeLock = () => 'wakeLock' in navigator;

export interface Fix {
  lngLat: LngLat;
  heading: number;
  speed: number;
  accuracy: number;
}

/** watchPosition every 2–3 s while the screen is on. */
export function watchLocation(onFix: (f: Fix) => void, onError: (msg: string) => void): () => void {
  if (!('geolocation' in navigator)) {
    onError('Location is not available on this device.');
    return () => undefined;
  }
  const id = navigator.geolocation.watchPosition(
    (p) =>
      onFix({
        lngLat: [p.coords.longitude, p.coords.latitude],
        heading: p.coords.heading ?? 0,
        speed: p.coords.speed ?? 0,
        accuracy: p.coords.accuracy,
      }),
    (e) => onError(e.message || 'Location permission denied.'),
    { enableHighAccuracy: true, maximumAge: 2000, timeout: 10000 },
  );
  return () => navigator.geolocation.clearWatch(id);
}

export function vibrate(pattern: number | number[]) {
  try {
    navigator.vibrate?.(pattern);
  } catch {
    /* iOS has no vibrate */
  }
}
