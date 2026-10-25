import { agentColor } from '../design/tokens'

// Placeholder agent badges (simple geometric icons). Swap for the Figma mascot SVGs once they are exported: keep the same `agent` keys.
const ICON: Record<string, JSX.Element> = {
  scout: <path d="M12 3l2.6 6.4L21 12l-6.4 2.6L12 21l-2.6-6.4L3 12l6.4-2.6z" fill="currentColor" />,
  watcher: <><path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12z" fill="none" stroke="currentColor" strokeWidth="2" /><circle cx="12" cy="12" r="3.2" fill="currentColor" /></>,
  rescuer: <path d="M12 3l8 3v6c0 5-3.4 8-8 9-4.6-1-8-4-8-9V6z" fill="none" stroke="currentColor" strokeWidth="2" />,
  reporter: <><rect x="5" y="3" width="14" height="18" rx="2" fill="none" stroke="currentColor" strokeWidth="2" /><path d="M8 9h8M8 13h8M8 17h5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" /></>,
  auditor: <path d="M20 14.5A8.5 8.5 0 119.5 4a7 7 0 0010.5 10.5z" fill="currentColor" />,
  place: <><path d="M4 10l1.5-5h13L20 10v2H4z" fill="currentColor" /><path d="M6 12v7h12v-7" fill="none" stroke="currentColor" strokeWidth="2" /></>,
  walk: <circle cx="12" cy="12" r="5" fill="currentColor" />,
}
export const AGENT_NAME: Record<string, string> = { scout: 'Scout', watcher: 'Watcher', rescuer: 'Rescuer', reporter: 'Reporter', auditor: 'Night Auditor', place: 'Place agents', walk: 'Walk' }

export function Avatar({ agent, size }: { agent: string; size?: 'lg' }) {
  const c = agentColor[agent] || '#7b8cf0'
  return <span className={`avatar ${size || ''}`} style={{ background: `${c}26`, color: c }} aria-hidden="true"><svg viewBox="0 0 24 24">{ICON[agent] || ICON.walk}</svg></span>
}
