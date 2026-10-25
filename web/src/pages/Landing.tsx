import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { Avatar, type AvatarState } from '../Avatar';
import { agents as getAgents, createPlan, health, type AgentInfo, type Health, type Plan } from '../lib/api';
import { JOB, PERSONA } from '../lib/personas';
import type { AgentName } from '../lib/types';
import { MapCanvas } from '../Map';
import { Brand, Icon } from '../ui';

const CREW: AgentName[] = ['head', 'guide', 'checker', 'rescuer'];
// The stage corridor, scored live by the engine (not a picture): Moscone Center → City Hall, Friday 11:30 PM.
const STAGE = { from: { name: 'Moscone Center', lngLat: [-122.4016, 37.7842] as [number, number] }, to: { name: 'City Hall', lngLat: [-122.4193, 37.7793] as [number, number] }, when: { day: 4, minute: 1410 } };

export default function Landing() {
  const [hp, setHp] = useState<Health | null>(null);
  const [crew, setCrew] = useState<AgentInfo[] | null>(null);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [beat, setBeat] = useState(0);

  useEffect(() => {
    void health().then(setHp).catch(() => setHp(null));
    void getAgents().then(setCrew).catch(() => setCrew(null));
    void createPlan(STAGE.from, STAGE.to, STAGE.when).then(setPlan).catch(() => setPlan(null));
    const t = setInterval(() => setBeat((b) => b + 1), 2200);
    return () => clearInterval(t);
  }, []);

  const routes = useMemo(() => (plan?.options ?? []).filter((o) => o.id !== 'balanced').map((o) => ({ id: o.id, coords: o.coords, active: o.id === 'best' })), [plan]);
  const best = plan?.stats.hootroute, fast = plan?.stats.shortest;
  const stateOf = (i: number): AvatarState => (beat % 4 === i ? 'talking' : 'idle');

  return (
    <div className="landing">
      <MapCanvas routes={routes} start={STAGE.from.lngLat} end={STAGE.to.lngLat} fitKey={plan?.planId ?? 'none'} cinematic interactive={false} pad={{ left: 0, bottom: 0 }} />
      <div className="landing__veil" />
      <nav className="landing__nav">
        <Brand />
        <Link className="btn btn--ghost btn--sm" to="/plan">Open the planner</Link>
      </nav>

      <div className="landing__wrap">
        <section className="hero">
          <span className="hero__kicker fade"><i /> {hp ? `${hp.engine?.segments?.toLocaleString() ?? ''} San Francisco street segments, scored live` : 'Agentic navigation for the journey after dark'}</span>
          <h1 className="fade">Your night shift<br />has a <em>wingman.</em></h1>
          <p className="fade">HootRoute plans the walk after a late class or a late shift by what is listed open, lit and running at the minute you pass each block. It checks what it doesn't know, asks before it spends, and stays with you when the plan changes.</p>
          <div className="hero__cta fade">
            <Link className="btn btn--primary btn--lg" to="/plan">Plan a journey <Icon name="arrow" size={17} /></Link>
            <a className="btn btn--ghost btn--lg" href="#crew">Meet the crew</a>
          </div>
          {best && fast && (
            <div className="stats fade" aria-label="Live engine result for the corridor on the map">
              <div><b>{best.score} <span style={{ color: 'var(--fg-3)' }}>vs</span> {fast.score}</b><span>HootRoute vs fastest, Moscone → City Hall, Fri 11:30 PM</span></div>
              <div><b>{best.longestEmptyM} m</b><span>longest stretch with nothing listed open (fastest: {fast.longestEmptyM} m)</span></div>
              <div><b>+{Math.max(0, best.minutes - fast.minutes).toFixed(1)} min</b><span>extra walking</span></div>
            </div>
          )}
        </section>

        <section className="section" id="crew">
          <span className="eyebrow">The crew</span>
          <h2>Four agents. One journey. Every number from the engine.</h2>
          <div className="agents">
            {CREW.map((id, i) => {
              const info = crew?.find((c) => c.id === id);
              return (
                <div key={id} className="agent-card reveal" style={{ animationDelay: `${i * 90}ms` }}>
                  <div className="between"><Avatar id={id} state={stateOf(i)} size={56} />{info && <span className={`badge ${info.live ? 'badge--mint' : 'badge--amber'}`}>{info.live ? 'live' : 'not configured'}</span>}</div>
                  <h3>{PERSONA[id]}</h3>
                  <p>{info?.job ?? JOB[id].job}</p>
                  <small>{info?.runsOn ?? JOB[id].runsOn}</small>
                </div>
              );
            })}
          </div>
        </section>

        <section className="section">
          <span className="eyebrow">How a journey works</span>
          <h2>Tell it where you're going. It handles the rest, and asks first.</h2>
          <div className="flow">
            <div><b>Ask in plain words</b><span>"Leaving the library at 11:40, to Civic Center BART, fewer turns." Professor Hoot picks the tools.</span></div>
            <div><b>Compare real routes</b><span>Scoot scores every candidate at the minute you pass each block: open places, gaps, lighting, transit, turns.</span></div>
            <div><b>Investigate the unknown</b><span>Sherlock finds places with unknown hours and checks their listings, but only after you approve.</span></div>
            <div><b>Walk with a wingman</b><span>Wally follows the route. Report a block and get alternatives; nothing changes until you choose.</span></div>
          </div>
        </section>

        <section className="section">
          <span className="eyebrow">Principles</span>
          <div className="rules">
            <span>Conditions, not a safety rating</span><span>No crime data, no neighbourhood grades</span><span>No model in the score</span>
            <span>Unknown stays unknown</span><span>Paid checks need your OK</span><span>Sharing is yours to stop</span><span>Never calls 911 for you</span>
          </div>
          <div className="footer-cta">
            <div className="row" style={{ gap: 14 }}><Avatar id="head" state="talking" size={48} /><div><b>Where to tonight?</b><div className="muted small">Pick a start and a destination anywhere in San Francisco.</div></div></div>
            <Link className="btn btn--primary btn--lg" to="/plan">Plan a journey <Icon name="arrow" size={17} /></Link>
          </div>
        </section>
      </div>
    </div>
  );
}
