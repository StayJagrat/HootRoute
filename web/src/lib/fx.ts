/** Pointer effects for the Nocturne UI: 3D tilt + glare on cards, a cursor tint on chips and a click ripple on buttons.
 *  One set of delegated listeners for the whole app; nothing runs for touch-only or reduced-motion users. */

const TILT = '.agent-card, .flow > div, .route, .kpi, .footer-cta';
const GLOW = '.btn, .chip';
const MAX_DEG = 7;

const reduced = () => matchMedia('(prefers-reduced-motion: reduce)').matches;
const finePointer = () => matchMedia('(hover: hover) and (pointer: fine)').matches;

let tilted: HTMLElement | null = null;

function resetTilt() {
  if (!tilted) return;
  tilted.style.removeProperty('--rx');
  tilted.style.removeProperty('--ry');
  tilted.classList.remove('is-tilting');
  tilted = null;
}

function onMove(e: PointerEvent) {
  const target = e.target as Element | null;
  const glow = target?.closest<HTMLElement>(GLOW);
  if (glow) {
    const r = glow.getBoundingClientRect();
    glow.style.setProperty('--mx', `${e.clientX - r.left}px`);
    glow.style.setProperty('--my', `${e.clientY - r.top}px`);
  }
  const card = target?.closest<HTMLElement>(TILT) ?? null;
  if (card !== tilted) resetTilt();
  if (!card) return;
  const r = card.getBoundingClientRect();
  const x = (e.clientX - r.left) / r.width, y = (e.clientY - r.top) / r.height;
  // Smaller tilt on wide cards so long rows don't swing too far.
  const k = Math.min(1, 320 / r.width);
  card.style.setProperty('--ry', `${((x - 0.5) * 2 * MAX_DEG * k).toFixed(2)}deg`);
  card.style.setProperty('--rx', `${((0.5 - y) * 2 * MAX_DEG * k).toFixed(2)}deg`);
  card.style.setProperty('--gx', `${(x * 100).toFixed(1)}%`);
  card.style.setProperty('--gy', `${(y * 100).toFixed(1)}%`);
  card.classList.add('is-tilting');
  tilted = card;
}

function onDown(e: PointerEvent) {
  const btn = (e.target as Element | null)?.closest<HTMLElement>('.btn');
  if (!btn || (btn as HTMLButtonElement).disabled) return;
  const r = btn.getBoundingClientRect();
  const size = Math.max(r.width, r.height) * 2;
  const dot = document.createElement('span');
  dot.className = 'ripple';
  dot.style.cssText = `width:${size}px;height:${size}px;left:${e.clientX - r.left - size / 2}px;top:${e.clientY - r.top - size / 2}px`;
  btn.appendChild(dot);
  dot.addEventListener('animationend', () => dot.remove(), { once: true });
}

export function initFx() {
  if (typeof window === 'undefined' || reduced()) return;
  document.addEventListener('pointerdown', onDown, { passive: true });
  if (!finePointer()) return;
  document.addEventListener('pointermove', onMove, { passive: true });
  document.addEventListener('pointerleave', resetTilt);
  window.addEventListener('blur', resetTilt);
}

/** Fade sections in as they scroll into view. Returns a cleanup. */
export function revealOnScroll(root: HTMLElement, selector: string): () => void {
  const items = Array.from(root.querySelectorAll<HTMLElement>(selector));
  if (reduced() || typeof IntersectionObserver === 'undefined') return () => {};
  root.classList.add('fx-reveal');
  const io = new IntersectionObserver((entries) => {
    for (const en of entries) if (en.isIntersecting) { en.target.classList.add('is-in'); io.unobserve(en.target); }
  }, { root, threshold: 0.12 });
  items.forEach((el) => io.observe(el));
  return () => { io.disconnect(); root.classList.remove('fx-reveal'); };
}
