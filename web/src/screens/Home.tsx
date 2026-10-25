import { Logo } from '../components/Logo';
import { Link, Navigate } from 'react-router-dom';
import { introSeen } from './Intro';
import { Mascot } from '../components/ui';
import { walkIdFromUrl } from '../lib/store';
import type { AgentName } from '../lib/types';

// Hub for the demo crew: one walk id, four screens.
export default function Home() {
  const w = walkIdFromUrl();
  if (!introSeen() && !new URLSearchParams(location.search).has('hub')) return <Navigate to="/welcome" replace />;
  const q = w ? `?walk=${encodeURIComponent(w)}` : '';
  const links: [string, string, string, AgentName][] = [
    [`/welcome`, 'How it works', 'The four agents, step by step', 'head'],
    [`/plan`, 'Plan a walk', 'Ask the Head, or pick any start and destination in San Francisco', 'head'],
    [`/setup`, 'Setup', 'Guardian, backup contact and standing orders', 'guide'],
    [`/walk${q}`, 'Walker', 'The demo phone with earbuds', 'checker'],
    ...(w ? [[`/guardian/${w}`, 'Guardian', "Opened from the QR on a judge's phone", 'rescuer'] as [string, string, string, AgentName]] : []),
    [`/shop${q}`, 'Shopkeeper', 'Simulated hours update for a place on the route', 'guide'],
    [`/room${q}`, 'Control room', 'The laptop on stage', 'head'],
  ];
  return (
    <div className="screen screen--scroll" data-theme="night">
      <main style={{ maxWidth: 520, margin: '0 auto', padding: 'calc(40px + var(--safe-top)) 20px 40px', display: 'flex', flexDirection: 'column', gap: 14 }}>
        <h1 style={{ margin: 0 }}><Logo size={34} /></h1>
        <p className="muted" style={{ margin: '0 0 8px' }}>{w ? <>A walking companion for late-shift workers. Walk <code>{w}</code>: every screen below joins the same room.</> : 'A walking companion for late-shift workers. No walk yet: plan one, or start the stage walk from the control room.'}</p>
        {links.map(([to, title, sub, a]) => (
          <Link key={to} to={to} className="card" style={{ display: 'flex', gap: 14, alignItems: 'center', padding: 14, textDecoration: 'none', color: 'var(--text)' }}>
            <Mascot agent={a} size={48} />
            <div>
              <div className="t-headline">{title}</div>
              <div className="t-caption">{sub}</div>
            </div>
          </Link>
        ))}
      </main>
    </div>
  );
}
