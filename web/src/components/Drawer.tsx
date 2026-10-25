import { useEffect, useRef, type ReactNode } from 'react';
import './drawer.css';

/** A panel over the map: a bottom sheet on phones, a side panel on desktop. Escape or the scrim closes it.
 *  Focus moves into the panel on open, Tab stays inside it, and focus returns where it was on close. */
export function Drawer({ open, onClose, title, children, label }: { open: boolean; onClose: () => void; title: ReactNode; children: ReactNode; label: string }) {
  const panel = useRef<HTMLElement>(null);
  const closeRef = useRef(onClose); closeRef.current = onClose;     // parents pass a new function every render; focus must not jump
  useEffect(() => {
    if (!open) return;
    const before = document.activeElement as HTMLElement | null;
    panel.current?.querySelector<HTMLElement>('.drawer__close')?.focus();
    const k = (e: KeyboardEvent) => {
      if (e.key === 'Escape') closeRef.current();
      if (e.key !== 'Tab' || !panel.current) return;
      const f = [...panel.current.querySelectorAll<HTMLElement>('button, [href], input, textarea, select, [tabindex]:not([tabindex="-1"])')].filter((x) => !x.hasAttribute('disabled'));
      if (!f.length) return;
      const first = f[0], last = f[f.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    };
    window.addEventListener('keydown', k);
    return () => { window.removeEventListener('keydown', k); before?.focus?.(); };
  }, [open]);
  if (!open) return null;
  return (
    <div className="drawer" role="dialog" aria-modal="true" aria-label={label}>
      <div className="drawer__scrim" onClick={onClose} />
      <section className="drawer__panel" ref={panel}>
        <div className="sheet__handle drawer__handle" aria-hidden />
        <header className="drawer__head">
          <div className="drawer__title">{title}</div>
          <button type="button" className="drawer__close" onClick={onClose} aria-label="Close">×</button>
        </header>
        <div className="drawer__body">{children}</div>
      </section>
    </div>
  );
}
