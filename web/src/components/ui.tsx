import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from 'react';
import { ICONS, type IconName } from './icons';
import { AGENT_LABEL, timeOf } from '../lib/format';
import type { AgentName, MascotState } from '../lib/types';
import { vibrate } from '../lib/device';
import './ui.css';

export function Icon({ name, size = 20, style, className }: { name: IconName; size?: number; style?: CSSProperties; className?: string }) {
  return <span className={`icon ${className ?? ''}`} style={{ width: size, height: size, ...style }} dangerouslySetInnerHTML={{ __html: ICONS[name] }} />;
}

/** The four agents: Head the owl, Guide the pigeon, Checker the raccoon, Rescuer the sea lion. */
const MASCOT_FILE: Record<AgentName, string> = { head: 'head', guide: 'guide', checker: 'checker', rescuer: 'rescuer' };

export function Mascot({ agent, state = 'idle', size = 44, alt }: { agent: AgentName; state?: MascotState; size?: number; alt?: string }) {
  return <img className={`mascot mascot--${state}`} src={`/mascots/${MASCOT_FILE[agent]}-${state}.svg`} width={size} height={size} alt={alt ?? AGENT_LABEL[agent]} draggable={false} />;
}

export function Sheet({ children, className, label }: { children: ReactNode; className?: string; label?: string }) {
  return (
    <section className={`sheet ${className ?? ''}`} aria-label={label}>
      <div className="sheet__handle" aria-hidden />
      {children}
    </section>
  );
}

type Kind = 'fine' | 'help' | 'primary' | 'secondary';
export function Button({ kind, children, onClick, icon, tall, block, disabled, ariaLabel }: { kind: Kind; children: ReactNode; onClick?: () => void; icon?: IconName; tall?: boolean; block?: boolean; disabled?: boolean; ariaLabel?: string }) {
  return (
    <button type="button" className={`btn btn--${kind}${tall ? ' btn--tall' : ''}${block ? ' btn--block' : ''}`} onClick={onClick} disabled={disabled} aria-label={ariaLabel}>
      {icon && <Icon name={icon} size={22} />}
      {children}
    </button>
  );
}

/** Press-and-hold (1.5 s) so a phone in a pocket can't call for help by accident. */
export function HoldButton({ kind = 'help', children, onConfirm, holdMs = 1500, tall, block }: { kind?: Kind; children: ReactNode; onConfirm: () => void; holdMs?: number; tall?: boolean; block?: boolean }) {
  const [p, setP] = useState(0);
  const raf = useRef<number>();
  const start = useRef<number>(0);
  const fired = useRef(false);
  const begin = () => {
    fired.current = false;
    start.current = performance.now();
    vibrate(10);
    const step = (t: number) => {
      const k = Math.min(1, (t - start.current) / holdMs);
      setP(k);
      if (k >= 1 && !fired.current) {
        fired.current = true;
        vibrate([30, 40, 60]);
        onConfirm();
        setTimeout(() => setP(0), 300);
        return;
      }
      raf.current = requestAnimationFrame(step);
    };
    raf.current = requestAnimationFrame(step);
  };
  const end = () => {
    if (raf.current) cancelAnimationFrame(raf.current);
    if (!fired.current) setP(0);
  };
  useEffect(() => () => {
    if (raf.current) cancelAnimationFrame(raf.current);
  }, []);
  const r = 9, c = 2 * Math.PI * r;
  return (
    <button
      type="button"
      className={`btn btn--${kind}${tall ? ' btn--tall' : ''}${block ? ' btn--block' : ''}`}
      onPointerDown={begin}
      onPointerUp={end}
      onPointerLeave={end}
      onPointerCancel={end}
      onContextMenu={(e) => e.preventDefault()}
      onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && !e.repeat && begin()}
      onKeyUp={end}
      aria-label="Press and hold for help"
    >
      <span className="btn__fill" style={{ transform: `scaleX(${p})` }} />
      <svg width="22" height="22" viewBox="0 0 24 24" aria-hidden>
        <circle cx="12" cy="12" r={r} fill="none" stroke="currentColor" strokeOpacity="0.35" strokeWidth="3" />
        <circle cx="12" cy="12" r={r} fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeDasharray={c} strokeDashoffset={c * (1 - Math.max(0.18, p))} transform="rotate(-90 12 12)" />
      </svg>
      {children}
    </button>
  );
}

export function StreetSign({ street, instruction, direction }: { street: string; instruction: string; direction: 'left' | 'right' | 'straight' | 'arrive' }) {
  const icon: IconName = direction === 'left' ? 'turnLeft' : direction === 'right' ? 'turnRight' : direction === 'arrive' ? 'star' : 'straight';
  return (
    <div className="street-sign" role="status" aria-live="polite">
      <Icon name={icon} size={28} />
      <div>
        <div className="street-sign__street t-sign">{street}</div>
        <div className="street-sign__instr">{instruction}</div>
      </div>
    </div>
  );
}

export function DemoTape({ label = 'DEMO · GPS REPLAY' }: { label?: string }) {
  return (
    <div className="demo-tape" title="This walk is a GPS replay, not a live walk">
      <span>{label}</span>
    </div>
  );
}

export function Toggle({ on, onChange, label }: { on: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <button type="button" role="switch" aria-checked={on} aria-label={label} className={`toggle${on ? ' toggle--on' : ''}`} onClick={() => onChange(!on)}>
      <span className="toggle__knob" />
    </button>
  );
}

export function Initials({ text, size = 28, color = '#EEA073' }: { text: string; size?: number; color?: string }) {
  return (
    <span className="avatar" style={{ width: size, height: size, background: color, fontSize: Math.round(size * 0.45) }} aria-hidden>
      {text}
    </span>
  );
}

export function AgentRow({ agent, state = 'talking', to, ts, text, reason }: { agent: AgentName; state?: MascotState; to?: string; ts: number; text: string; reason: string }) {
  return (
    <article className="agent-row">
      <Mascot agent={agent} state={state} size={40} />
      <div className="agent-row__body">
        <header className="agent-row__head">
          <strong>{AGENT_LABEL[agent]}</strong>
          {to && <span className="agent-row__to">→ {to}</span>}
          <span className="t-mono agent-row__time">{timeOf(ts, true)}</span>
        </header>
        <p className="agent-row__text">{text}</p>
        <p className="agent-row__why">why: {reason}</p>
      </div>
    </article>
  );
}

export function LinkBadge({ status }: { status: 'connecting' | 'online' | 'local' }) {
  const label = status === 'online' ? 'Live room' : status === 'connecting' ? 'Connecting…' : 'This device only';
  return (
    <span className={`link-badge link-badge--${status}`} title={status === 'local' ? 'No gateway/relay reachable — syncing between tabs on this device only' : 'Connected to the walk room'}>
      <span className="dot" /> {label}
    </span>
  );
}
