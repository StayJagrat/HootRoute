import type { ReactNode } from 'react';
import { Avatar, type AvatarState } from './Avatar';
import { PERSONA } from './lib/personas';
import type { AgentName } from './lib/types';

const PATHS: Record<string, string> = {
  search: 'M11 4a7 7 0 1 0 4.9 12l4.1 4.1M11 4a7 7 0 0 1 0 14',
  locate: 'M12 3v3m0 12v3M3 12h3m12 0h3M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8Z',
  arrow: 'M5 12h14m-6-6 6 6-6 6',
  back: 'M19 12H5m6 6-6-6 6-6',
  left: 'M14 5 7 12l7 7M7 12h12',
  right: 'M10 5l7 7-7 7M17 12H5',
  straight: 'M12 20V4m-6 6 6-6 6 6',
  check: 'm5 12 4.5 4.5L19 7',
  x: 'M6 6l12 12M18 6 6 18',
  share: 'M12 3v12m0-12-4 4m4-4 4 4M5 13v6a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-6',
  flag: 'M5 21V4m0 0h11l-2 4 2 4H5',
  alert: 'M12 8v5m0 3.5v.5M10.3 3.9 2.6 17.5A2 2 0 0 0 4.3 20.5h15.4a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z',
  spark: 'M12 3v4m0 10v4M3 12h4m10 0h4M6 6l2.5 2.5m7 7L18 18M18 6l-2.5 2.5m-7 7L6 18',
  clock: 'M12 7v5l3 2M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18Z',
  swap: 'M7 4v16m0 0-3-3m3 3 3-3M17 20V4m0 0-3 3m3-3 3 3',
  dots: 'M5 12h.01M12 12h.01M19 12h.01',
};

export function Icon({ name, size = 18, stroke = 1.7 }: { name: keyof typeof PATHS | string; size?: number; stroke?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={stroke} strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d={PATHS[name] ?? PATHS.dots} />
    </svg>
  );
}

/** Wordmark: a crescent moon over a path. No mascots in the product UI. */
export function Brand({ sub }: { sub?: string }) {
  return (
    <div className="brand">
      <span className="brand__mark" aria-hidden>
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
          <path d="M15.5 3.5a8.5 8.5 0 1 0 5 15.3A7 7 0 0 1 15.5 3.5Z" fill="#a9c1ff" />
        </svg>
      </span>
      <span>HootRoute {sub && <small>{sub}</small>}</span>
    </div>
  );
}

export function Toggle({ on, onChange, label }: { on: boolean; onChange: (v: boolean) => void; label: string }) {
  return <button type="button" role="switch" aria-checked={on} aria-label={label} className="toggle" onClick={() => onChange(!on)} />;
}

/** A persona with its animated avatar, e.g. Professor Hoot. */
export function Agent({ id, state = 'idle', children }: { id: AgentName; state?: AvatarState; children?: ReactNode }) {
  return (
    <span className="row" style={{ gap: 8 }}>
      <Avatar id={id} state={state} size={26} label={false} />
      <span style={{ fontWeight: 600, fontSize: 13 }}>{PERSONA[id]}</span>
      {children}
    </span>
  );
}

export function Spinner({ label }: { label: string }) {
  return <span className="row small muted" role="status"><span className="spin" />{label}</span>;
}
