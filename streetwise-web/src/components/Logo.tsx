import type { CSSProperties } from 'react';
import './logo.css';
import { BRAND } from '../lib/brand';

// The HootRoute owl: the walk home as a dashed route ending at the green destination dot.
// Same artwork as public/brand/hootroute-mark.svg and the app icons.
export function LogoMark({ size = 40, label }: { size?: number; label?: string }) {
  return (
    <svg className="logo-mark" width={size} height={size} viewBox="0 0 1024 1024" role={label ? 'img' : undefined} aria-label={label} aria-hidden={label ? undefined : true}>
      <rect width="1024" height="1024" rx="220" fill="#121B33" />
      <path d="M168 742 C180 660 210 590 270 530 C330 470 420 430 560 405 C660 388 740 360 800 320 L842 262" fill="none" stroke="#7FA6EE" strokeWidth="28" strokeLinecap="round" strokeDasharray="44 38" />
      <circle cx="842" cy="260" r="52" fill="#A6EFCB" />
      <path d="M192 420 L383 465 L505 383 L632 465 L828 425 L722 625 C690 735 610 792 505 795 C400 792 318 735 290 630 Z" fill="#A9C8FA" stroke="#FFFFFF" strokeWidth="18" strokeLinejoin="round" />
      <circle cx="418" cy="580" r="97" fill="#121B33" />
      <circle cx="592" cy="580" r="97" fill="#121B33" />
      <circle cx="421" cy="577" r="32" fill="#FFFFFF" />
      <circle cx="597" cy="574" r="32" fill="#FFFFFF" />
      <path d="M470 665 L540 665 L505 718 Z" fill="#F2B44C" />
      {size >= 28 && <path d="M383 745 Q505 800 625 745" fill="none" stroke="#121B33" strokeWidth="14" strokeLinecap="round" />}
    </svg>
  );
}

// The brand name in lowercase; the last word takes the route colour ("hoot" + "route").
export function Wordmark({ size = 20, style }: { size?: number; style?: CSSProperties }) {
  const name = BRAND.toLowerCase(); const cut = name.endsWith('route') ? name.length - 5 : name.length;
  return (
    <span className="wordmark" style={{ fontSize: size, ...style }} aria-label={BRAND} role="img">
      {name.slice(0, cut)}<span style={{ color: 'var(--route)' }}>{name.slice(cut)}</span>
    </span>
  );
}

export function Logo({ size = 20, mark, style }: { size?: number; mark?: number; style?: CSSProperties }) {
  return (
    <span className="logo" style={{ gap: Math.round(size * 0.35), ...style }}>
      <LogoMark size={mark ?? Math.round(size * 1.6)} />
      <Wordmark size={size} />
    </span>
  );
}
