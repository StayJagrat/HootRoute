import type { LngLat, RouteStep } from './types';

const R = 6371000;
const rad = (d: number) => (d * Math.PI) / 180;

export function distance(a: LngLat, b: LngLat): number {
  const dLat = rad(b[1] - a[1]);
  const dLng = rad(b[0] - a[0]);
  const s = Math.sin(dLat / 2) ** 2 + Math.cos(rad(a[1])) * Math.cos(rad(b[1])) * Math.sin(dLng / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(s));
}

export function bearing(a: LngLat, b: LngLat): number {
  const y = Math.sin(rad(b[0] - a[0])) * Math.cos(rad(b[1]));
  const x = Math.cos(rad(a[1])) * Math.sin(rad(b[1])) - Math.sin(rad(a[1])) * Math.cos(rad(b[1])) * Math.cos(rad(b[0] - a[0]));
  return ((Math.atan2(y, x) * 180) / Math.PI + 360) % 360;
}

export function lineLength(line: LngLat[]): number {
  let d = 0;
  for (let i = 1; i < line.length; i++) d += distance(line[i - 1], line[i]);
  return d;
}

/** Cumulative distance at each vertex. */
export function cumulative(line: LngLat[]): number[] {
  const out = [0];
  for (let i = 1; i < line.length; i++) out.push(out[i - 1] + distance(line[i - 1], line[i]));
  return out;
}

export interface Along {
  lngLat: LngLat;
  heading: number;
  index: number; // segment start index
}

export function along(line: LngLat[], meters: number, cum = cumulative(line)): Along {
  const total = cum[cum.length - 1];
  const m = Math.max(0, Math.min(total, meters));
  let i = 1;
  while (i < cum.length - 1 && cum[i] < m) i++;
  const a = line[i - 1];
  const b = line[i];
  const seg = cum[i] - cum[i - 1] || 1;
  const t = (m - cum[i - 1]) / seg;
  return { lngLat: [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t], heading: bearing(a, b), index: i - 1 };
}

/** Line from start up to `meters` along it (used to dim the travelled part of the route). */
export function sliceTo(line: LngLat[], meters: number, cum = cumulative(line)): LngLat[] {
  const p = along(line, meters, cum);
  return [...line.slice(0, p.index + 1), p.lngLat];
}

export function sliceFrom(line: LngLat[], meters: number, cum = cumulative(line)): LngLat[] {
  const p = along(line, meters, cum);
  return [p.lngLat, ...line.slice(p.index + 1)];
}

/** Distance along `line` of the vertex/projection closest to `p` (equirectangular, fine at city scale). */
export function project(line: LngLat[], p: LngLat, cum = cumulative(line)): { meters: number; offset: number } {
  const kx = Math.cos(rad(p[1])) * 111320;
  const ky = 110540;
  let best = { meters: 0, offset: Infinity };
  for (let i = 1; i < line.length; i++) {
    const ax = line[i - 1][0] * kx, ay = line[i - 1][1] * ky;
    const bx = line[i][0] * kx, by = line[i][1] * ky;
    const px = p[0] * kx, py = p[1] * ky;
    const dx = bx - ax, dy = by - ay;
    const L = dx * dx + dy * dy || 1;
    const t = Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / L));
    const qx = ax + t * dx, qy = ay + t * dy;
    const off = Math.hypot(px - qx, py - qy);
    if (off < best.offset) best = { meters: cum[i - 1] + t * Math.sqrt(L), offset: off };
  }
  return best;
}

/** Offset a point sideways (meters, + = right of heading). */
export function offsetPoint(p: LngLat, heading: number, meters: number): LngLat {
  const h = rad(heading + 90);
  const dx = (Math.sin(h) * meters) / (Math.cos(rad(p[1])) * 111320);
  const dy = (Math.cos(h) * meters) / 110540;
  return [p[0] + dx, p[1] + dy];
}

export function bounds(lines: LngLat[][]): [LngLat, LngLat] {
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (const l of lines) for (const [x, y] of l) {
    minX = Math.min(minX, x); minY = Math.min(minY, y); maxX = Math.max(maxX, x); maxY = Math.max(maxY, y);
  }
  return [[minX, minY], [maxX, maxY]];
}

export interface Turn {
  meters: number; // distance along route of the corner
  direction: 'left' | 'right' | 'arrive';
  street: string; // street you turn onto
}

/** Corners where the bearing changes by more than 50°, labelled with the next street name. */
export function turns(line: LngLat[], streets: string[]): Turn[] {
  const cum = cumulative(line);
  const out: Turn[] = [];
  let lastBearing: number | null = null;
  let lastTurnAt = -Infinity;
  for (let i = 1; i < line.length - 1; i++) {
    const segLen = cum[i + 1] - cum[i];
    if (segLen < 6) continue;
    const b0 = lastBearing ?? bearing(line[i - 1], line[i]);
    const b1 = bearing(line[i], line[i + 1]);
    let d = ((b1 - b0 + 540) % 360) - 180;
    if (Math.abs(d) > 50 && cum[i] - lastTurnAt > 60) {
      out.push({ meters: cum[i], direction: d > 0 ? 'right' : 'left', street: '' });
      lastTurnAt = cum[i];
      lastBearing = b1;
    } else if (Math.abs(d) <= 50) {
      lastBearing = b1;
    }
  }
  out.forEach((t, k) => (t.street = streets[k + 1] ?? ''));
  out.push({ meters: cum[cum.length - 1], direction: 'arrive', street: 'HOME' });
  return out;
}

/** Use the engine's named street steps for the cached pilot route. */
export function turnsFromSteps(steps: RouteStep[], length: number): Turn[] {
  const out: Turn[] = steps
    .filter((s) => /left|right/.test(s.maneuver))
    .map((s) => ({ meters: s.at_m, direction: s.maneuver.includes('left') ? 'left' : 'right', street: s.street === 'the path' ? 'walking path' : s.street }));
  out.push({ meters: length, direction: 'arrive', street: 'DESTINATION' });
  return out;
}
