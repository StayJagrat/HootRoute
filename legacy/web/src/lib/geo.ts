import type { LL } from '../api/types'

const M_LAT = 110540
export const mPerLon = (lat: number) => 111320 * Math.cos((lat * Math.PI) / 180)
export function dist(a: LL, b: LL) { return Math.hypot((a[0] - b[0]) * mPerLon(a[1]), (a[1] - b[1]) * M_LAT) }
export function cumulative(coords: LL[]) { const c = [0]; for (let i = 1; i < coords.length; i++) c.push(c[i - 1] + dist(coords[i - 1], coords[i])); return c }
/** Point at distance d (metres) along a polyline, plus the heading in degrees. */
export function pointAt(coords: LL[], cum: number[], d: number): { ll: LL; bearing: number } {
  const total = cum[cum.length - 1]; const t = Math.max(0, Math.min(d, total)); let i = 1
  while (i < cum.length - 1 && cum[i] < t) i++
  const seg = Math.max(cum[i] - cum[i - 1], 1e-6); const f = (t - cum[i - 1]) / seg
  const a = coords[i - 1], b = coords[i]
  const ll: LL = [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f]
  const bearing = (Math.atan2((b[0] - a[0]) * mPerLon(a[1]), (b[1] - a[1]) * M_LAT) * 180) / Math.PI
  return { ll, bearing }
}
export function slice(coords: LL[], cum: number[], from: number, to: number): LL[] {
  const out: LL[] = [pointAt(coords, cum, from).ll]
  for (let i = 0; i < coords.length; i++) if (cum[i] > from && cum[i] < to) out.push(coords[i])
  out.push(pointAt(coords, cum, to).ll); return out
}
export const fmtClock = (minute: number) => { const m = Math.round(minute); const h = Math.floor(m / 60) % 24; return `${h % 12 || 12}:${String(m % 60).padStart(2, '0')} ${h >= 12 ? 'PM' : 'AM'}` }
export const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
