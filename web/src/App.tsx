import { useEffect, useState } from 'react';
import { Navigate, Route, Routes } from 'react-router-dom';
import { Loader } from './Avatar';
import { health } from './lib/api';
import Guardian from './pages/Guardian';
import Landing from './pages/Landing';
import Plan from './pages/Plan';
import Walk from './pages/Walk';

const LINES = ['Waking the night crew…', 'Loading 139,515 street segments…', 'Checking who is listed open…'];

/** Splash while the gateway answers (at least a beat, at most a few seconds). */
function Splash({ children }: { children: React.ReactNode }) {
  const [phase, setPhase] = useState<'in' | 'out' | 'gone'>('in');
  const [i, setI] = useState(0);
  useEffect(() => {
    const t0 = Date.now(); let done = false;
    const finish = () => { if (done) return; done = true; setTimeout(() => setPhase('out'), Math.max(0, 1300 - (Date.now() - t0))); };
    void health().then(finish, finish);
    const cap = setTimeout(finish, 4000);
    const rot = setInterval(() => setI((x) => (x + 1) % LINES.length), 900);
    return () => { clearTimeout(cap); clearInterval(rot); };
  }, []);
  useEffect(() => { if (phase === 'out') { const t = setTimeout(() => setPhase('gone'), 600); return () => clearTimeout(t); } }, [phase]);
  return (
    <>
      {children}
      {phase !== 'gone' && <div className={phase === 'out' ? 'loader--out' : ''} style={{ position: 'fixed', inset: 0, zIndex: 50 }}><Loader text={LINES[i]} /></div>}
    </>
  );
}

export default function App() {
  return (
    <Splash>
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route path="/plan" element={<Plan />} />
        <Route path="/walk" element={<Walk />} />
        <Route path="/guardian/:walk" element={<Guardian />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Splash>
  );
}
