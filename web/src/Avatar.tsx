import type { AgentName } from './lib/types';

export type AvatarState = 'idle' | 'thinking' | 'talking' | 'done';

/** The four HootRoute agents as geometric owls. One silhouette, one colour and one emblem each:
 *  Professor Hoot (moon, orchestrates) · Scoot McRoute (path, routes) · Sherlock Hoots (lens, evidence) · Wingman Wally (wing, journey). */
export const AGENT_HUE: Record<AgentName, string> = { head: '#a9c1ff', guide: '#e9edf5', checker: '#f3b75e', rescuer: '#63e2b4' };

function Emblem({ id, c }: { id: AgentName; c: string }) {
  if (id === 'head') return <path d="M64 15a9 9 0 1 0 6 15.7A7.4 7.4 0 0 1 64 15Z" fill={c} />;
  if (id === 'guide') return <path d="M50 33c4-8 10-12 15-10s9 0 13-6" stroke={c} strokeWidth="2.4" strokeLinecap="round" strokeDasharray="0.1 5" fill="none" />;
  if (id === 'checker') return <g stroke={c} strokeWidth="2.6" fill="none" strokeLinecap="round"><circle cx="66" cy="22" r="6" /><path d="m70.5 26.5 5 5" /></g>;
  return <path d="M53 30c6-11 17-14 25-10-6 1-10 5-12 10-4-3-9-3-13 0Z" fill={c} />;
}

export function Avatar({ id, state = 'idle', size = 48, label = true }: { id: AgentName; state?: AvatarState; size?: number; label?: boolean }) {
  const c = AGENT_HUE[id];
  return (
    <span className={`av av--${state}`} style={{ width: size, height: size, ['--hue' as string]: c }} role={label ? 'img' : undefined} aria-hidden={!label}>
      <svg viewBox="0 0 96 96" width={size} height={size} fill="none">
        <circle className="av__ring" cx="48" cy="48" r="45" stroke={c} strokeOpacity="0.35" strokeWidth="1.5" strokeDasharray="5 9" />
        <g className="av__body">
          <path d="M24 34 L36 40 L48 30 L60 40 L72 34 L68 58 C65 70 57 76 48 76 C39 76 31 70 28 58 Z" fill="#121926" stroke={c} strokeOpacity="0.9" strokeWidth="2" strokeLinejoin="round" />
          <g className="av__eyes">
            <circle cx="39.5" cy="51" r="7.5" fill="#06080c" stroke={c} strokeWidth="1.6" />
            <circle cx="56.5" cy="51" r="7.5" fill="#06080c" stroke={c} strokeWidth="1.6" />
            <circle className="av__pupil" cx="40.5" cy="51" r="2.9" fill={c} />
            <circle className="av__pupil" cx="57.5" cy="51" r="2.9" fill={c} />
          </g>
          <path d="M45.5 59 L48 63 L50.5 59 Z" fill={c} />
          <Emblem id={id} c={c} />
        </g>
        <circle className="av__done" cx="76" cy="76" r="9" fill="#63e2b4" />
        <path className="av__done" d="m71.5 76 3 3 5.5-6" stroke="#06080c" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    </span>
  );
}

/** The splash while the app wakes up. */
export function Loader({ text }: { text: string }) {
  return (
    <div className="loader" role="status" aria-live="polite">
      <div className="loader__orbit">
        <Avatar id="head" state="thinking" size={88} label={false} />
        {(['guide', 'checker', 'rescuer'] as AgentName[]).map((a, i) => (
          <span key={a} className="loader__sat" style={{ ['--i' as string]: i }}><Avatar id={a} size={30} label={false} /></span>
        ))}
      </div>
      <div className="loader__word">HootRoute</div>
      <div className="loader__text">{text}</div>
    </div>
  );
}
