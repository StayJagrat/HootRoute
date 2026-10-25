import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { LogoMark, Wordmark } from '../components/Logo';
import { Button, Mascot } from '../components/ui';
import { BRAND } from '../lib/brand';
import type { AgentName } from '../lib/types';
import { PERSONA } from '../lib/personas';
import './intro.css';

/** First-run walkthrough: the four agents in the order they work for you. */
const STEPS: { agent: AgentName; n: string; name: string; title: string; body: string }[] = [
  { agent: 'guide', n: '1', name: PERSONA.guide, title: 'Picks the better street',
    body: 'Scores the fastest route and better ones by what is listed open, mapped as lit and reachable at the minute you pass each block. Re-plans around anything you report.' },
  { agent: 'checker', n: '2', name: PERSONA.checker, title: 'Checks the evidence',
    body: 'Finds places on the route whose hours are unknown or stale and, only after you approve, checks their published listings. Every hour shown says where it came from and when.' },
  { agent: 'rescuer', n: '3', name: PERSONA.rescuer, title: 'Stays with you on the walk',
    body: 'Takes obstacle reports and offers other routes for you to choose. Checks in if you stop. You can turn guardian sharing on or off; texts and calls go out only if you opt in.' },
  { agent: 'head', n: '4', name: PERSONA.head, title: 'Runs the crew and explains it',
    body: 'Reads what you ask in plain words, sends the others to work, asks before any paid check, and explains every choice with numbers from the tools.' },
];

export function introSeen(): boolean {
  try { return localStorage.getItem('hootroute:intro') === '1'; } catch { return true; }
}
function markSeen() { try { localStorage.setItem('hootroute:intro', '1'); } catch { /* storage blocked */ } }

export default function Intro() {
  const nav = useNavigate();
  const [i, setI] = useState(-1);          // -1 = welcome card
  const done = () => { markSeen(); nav('/plan'); };
  const s = i >= 0 ? STEPS[i] : null;
  return (
    <div className="screen intro" data-theme="night">
      <button type="button" className="intro__skip t-caption" onClick={done}>Skip</button>
      {!s ? (
        <main className="intro__body">
          <LogoMark size={120} label={`${BRAND} logo`} />
          <h1 className="intro__brand"><Wordmark size={40} /></h1>
          <p className="intro__tag">Your night shift has a wingman.</p>
          <p className="intro__lead">A walking companion for late-shift workers in San Francisco. Four agents work for you on every walk home.</p>
          <div className="intro__crew" aria-hidden>{STEPS.map((x) => <Mascot key={x.agent} agent={x.agent} size={52} />)}</div>
          <Button kind="primary" block onClick={() => setI(0)}>Meet the crew</Button>
          <p className="t-caption intro__fine">Conditions, not a safety rating. No crime data. {BRAND} never calls 911 for you.</p>
        </main>
      ) : (
        <main className="intro__body">
          <div className="intro__steps" role="tablist" aria-label="Walkthrough">
            {STEPS.map((x, k) => <span key={x.agent} className={`intro__dot${k === i ? ' on' : k < i ? ' done' : ''}`} />)}
          </div>
          <Mascot agent={s.agent} state="talking" size={150} />
          <div className="intro__n t-number">STEP {s.n} · {s.name.toUpperCase()}</div>
          <h2 className="t-display intro__title">{s.title}</h2>
          <p className="intro__text">{s.body}</p>
          <div className="btn-row">
            <Button kind="secondary" onClick={() => setI(i - 1)}>Back</Button>
            {i < STEPS.length - 1 ? <Button kind="primary" onClick={() => setI(i + 1)}>Next</Button> : <Button kind="primary" onClick={done}>Plan my walk</Button>}
          </div>
        </main>
      )}
    </div>
  );
}
