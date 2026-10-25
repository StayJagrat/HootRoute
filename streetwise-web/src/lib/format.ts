import type { AgentName, Place } from './types';

export const AGENT_LABEL: Record<AgentName, string> = {
  head: 'Head',
  guide: 'Guide',
  checker: 'Checker',
  rescuer: 'Rescuer',
};

export function openLabel(p: Pick<Place, 'openUntil' | 'kind'>): string {
  const u = p.openUntil;
  if (u === 'closed') return 'Closed';
  if (u === '24h') return 'Open 24h';
  if (u === 'lobby') return 'Lobby open';
  return `Open till ${clock(u)}`;
}

export function openSpoken(p: Pick<Place, 'openUntil'>): string {
  const u = p.openUntil;
  if (u === '24h') return 'open all night';
  if (u === 'lobby') return 'with the lobby open';
  if (u === 'closed') return 'closed';
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
