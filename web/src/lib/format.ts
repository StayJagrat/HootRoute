import type { AgentName, Place } from './types';
import { PERSONA } from './personas';

export const AGENT_LABEL: Record<AgentName, string> = PERSONA;

/** Listed open when you pass. Unknown hours are not open and not closed. */
export const isListedOpen = (u: string) => u !== 'closed' && u !== 'unknown';

export function openLabel(p: Pick<Place, 'openUntil' | 'kind'>): string {
  const u = p.openUntil;
  if (u === 'closed') return 'Closed';
  if (u === 'unknown') return 'Hours unknown';
  if (u === '24h') return 'Open 24h';
  if (u === 'lobby') return 'Lobby open';
  return `Open till ${clock(u)}`;
}

export function openSpoken(p: Pick<Place, 'openUntil'>): string {
  const u = p.openUntil;
  if (u === '24h') return 'open all night';
  if (u === 'lobby') return 'with the lobby open';
  if (u === 'closed') return 'closed';
  if (u === 'unknown') return 'with unknown hours';
  return `open till ${clock(u)}`;
}

/** "01:00" → "1 AM", "00:00" → "midnight", "23:30" → "11:30 PM" */
export function clock(hhmm: string): string {
  const [h, m] = hhmm.split(':').map(Number);
  if (Number.isNaN(h)) return hhmm;
  if (h === 0 && m === 0) return 'midnight';
  const suf = h >= 12 ? 'PM' : 'AM';
  const hh = h % 12 === 0 ? 12 : h % 12;
  return m ? `${hh}:${String(m).padStart(2, '0')} ${suf}` : `${hh} ${suf}`;
}

export function timeOf(ts: number, seconds = false): string {
  const d = new Date(ts);
  const h = d.getHours();
  const hh = h % 12 === 0 ? 12 : h % 12;
  const mm = String(d.getMinutes()).padStart(2, '0');
  const ss = String(d.getSeconds()).padStart(2, '0');
  return seconds ? `${String(h).padStart(2, '0')}:${mm}:${ss}` : `${hh}:${mm} ${h >= 12 ? 'PM' : 'AM'}`;
}

export function meters(m: number): string {
  if (m >= 1000) return `${(m / 1000).toFixed(1)} km`;
  return `${Math.max(10, Math.round(m / 10) * 10)} m`;
}

export function minutesText(min: number): string {
  return `${Math.max(1, Math.round(min))} min`;
}

/** Minute of the day (may exceed 1440) → "11:30 PM". */
export function clockOfMinute(minute: number): string {
  const m = ((Math.round(minute) % 1440) + 1440) % 1440;
  const h = Math.floor(m / 60);
  return `${h % 12 || 12}:${String(m % 60).padStart(2, '0')} ${h < 12 ? 'AM' : 'PM'}`;
}

/** ISO time → "Oct 24, 9:14 PM" (or the raw string if it doesn't parse). */
export function whenText(iso: string | null | undefined): string {
  if (!iso) return 'time unknown';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
}

/** Only http(s) links are ever rendered as links. */
export function safeUrl(u: string | null | undefined): string | null {
  if (!u) return null;
  try {
    const x = new URL(u);
    return x.protocol === 'http:' || x.protocol === 'https:' ? x.href : null;
  } catch {
    return null;
  }
}
