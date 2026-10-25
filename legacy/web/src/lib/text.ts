import type { Route } from '../api/types'
import { fmtClock } from './geo'

/** "Mo-Su 11:00-02:00" -> "2 AM". Returns null when the hours cannot be read. */
export function closeTime(hours: string | null): string | null {
  if (!hours) return null; if (hours.trim() === '24/7') return 'all night'
  const m = [...hours.matchAll(/(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})/g)]; if (!m.length) return null
  const l = m[m.length - 1]; let h = parseInt(l[3], 10) % 24; const mm = l[4]
  return `${h % 12 || 12}${mm === '00' ? '' : ':' + mm} ${h >= 12 ? 'PM' : 'AM'}`
}
export function scoutLine(best: Route, fast: Route): string {
  if (best.id === fast.id) return `This is already the best-scoring route I found. Nothing nearby beats it by enough to be worth extra walking.`
  const delta = best.minutes - fast.minutes
  const shop = best.shops.find((s) => s.name && closeTime(s.hours) && closeTime(s.hours) !== 'all night') || best.shops.find((s) => s.name)
  const gap = best.gap.m < fast.gap.m ? `its longest stretch with nothing open is ${best.gap.m} m instead of ${fast.gap.m} m` : `it passes ${best.places_open} open places instead of ${fast.places_open}`
  const close = shop && closeTime(shop.hours)
  return `This way is ${delta.toFixed(1)} min longer, but ${gap}.${shop ? ` ${shop.name} is open${close ? ` till ${close}` : ''}.` : ''}`
}
export const homeBy = (minute: number, minutes: number) => fmtClock(minute + minutes)
