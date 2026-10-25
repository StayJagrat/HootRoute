import { useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { Avatar, type AvatarState } from '../Avatar';
import { revealOnScroll } from '../lib/fx';
import { agents as getAgents, createPlan, health, type AgentInfo, type Health, type Plan } from '../lib/api';
import { JOB, PERSONA } from '../lib/personas';
import type { AgentName } from '../lib/types';
import { MapCanvas } from '../Map';
import { Brand, Icon } from '../ui';

const CREW: AgentName[] = ['head', 'guide', 'checker', 'rescuer'];
const RULES = ['Conditions, not a safety rating', 'No crime data, no neighbourhood grades', 'No model in the score', 'Unknown stays unknown', 'Paid checks need your OK', 'Sharing is yours to stop', 'Never calls 911 for you'];
// One example journey, scored live by the engine when the page opens (not a picture or a stored number).
const STAGE = { from: { name: 'Moscone Center', lngLat: [-122.4016, 37.7842] as [number, number] }, to: { name: 'Ferry Building', lngLat: [-122.3937, 37.7955] as [number, number] }, when: { day: 4, minute: 1410 } };

export default function Landing() {
  const [hp, setHp] = useState<Health | null>(null);
  const [crew, setCrew] = useState<AgentInfo[] | null>(null);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [beat, setBeat] = useState(0);
  const page = useRef<HTMLDivElement>(null);
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => (page.current ? revealOnScroll(page.current, '.section') : undefined), []);

  useEffect(() => {
    void health().then(setHp).catch(() => setHp(null));
    void getAgents().then(setCrew).catch(() => setCrew(null));
    void createPlan(STAGE.from, STAGE.to, STAGE.when).then(setPlan).catch(() => setPlan(null));
    const t = setInterval(() => setBeat((b) => b + 1), 2200);
    return () => clearInterval(t);
  }, []);

  const routes = useMemo(() => (plan?.options ?? []).filter((o) => o.id !== 'balanced').map((o) => ({ id: o.id, coords: o.coords, active: o.id === 'best' })), [plan]);
  const best = plan?.options?.find((o) => o.id === 'best'), fast = plan?.options?.find((o) => o.id === 'fast');
  const stateOf = (i: number): AvatarState => (beat % 4 === i ? 'talking' : 'idle');

  return (
    <div className="landing" ref={page} onScroll={(e) => setScrolled(e.currentTarget.scrollTop > 24)}>
      <MapCanvas routes={routes} start={STAGE.from.lngLat} end={STAGE.to.lngLat} fitKey={plan?.planId ?? 'none'} cinematic interactive={false} pad={{ left: 0, bottom: 0 }} />
      <div className="landing__veil" />
      <nav className={`landing__nav ${scrolled ? 'landing__nav--solid' : ''}`}>
        <div className="landing__bar">
          <Brand />
          <div className="landing__links">
            <a href="#how">How it works</a>
            <a href="#crew">The crew</a>
            <Link className="btn btn--primary btn--sm" to="/plan">Open the planner</Link>
          </div>
        </div>
      </nav>

      <header className="lp-hero">
        <div className="lp-col lp-hero__grid">
          <div className="lp-hero__copy">
            <p className="lp-stamp"><i aria-hidden />San Francisco · after 11 PM{hp?.engine?.segments ? <span className="lp-stamp__extra"> · {hp.engine.segments.toLocaleString()} street segments</span> : null}</p>
            <h1>Your night shift has a <span className="lp-mark">wingman.</span></h1>
            <p className="lp-lede">HootRoute plans the walk after a late class or a late shift by what is listed open, lit and running at the minute you pass each block. It checks what it doesn't know, asks before it spends, and stays with you when the plan changes.</p>
            <div className="lp-actions">
              <Link className="btn btn--primary btn--lg" to="/plan">Plan a journey <Icon name="arrow" size={17} /></Link>
              <a className="lp-textlink" href="#how">See how a walk goes</a>
            </div>
          </div>

          <aside className="ticket" aria-label="Live engine result for the corridor on the map">
            <div className="ticket__top">
              <span>Example · scored live</span>
              <span className="mono">FRI 11:30 PM</span>
            </div>
            <div className="ticket__trip"><b>{STAGE.from.name}</b><span>to</span><b>{STAGE.to.name}</b></div>
            {best && fast ? (
              <>
                <div className="ticket__rows">
                  {[best, fast].map((o) => (
                    <div key={o.id} className={`ticket__row ${o.id === 'best' ? 'ticket__row--on' : ''}`}>
                      <span className="ticket__name">{o.id === 'best' ? 'HootRoute' : 'Fastest'}</span>
                      <span className="ticket__bar"><i style={{ width: `${o.stats.score}%` }} /></span>
                      <span className="ticket__score mono">{o.stats.score}</span>
                      <span className="ticket__meta">{o.stats.minutes.toFixed(0)} min · longest empty stretch {o.stats.longestEmptyM} m</span>
                    </div>
                  ))}
                </div>
                <p className="ticket__note">
                  {Math.max(0, best.stats.minutes - fast.stats.minutes).toFixed(1)} extra minutes
                  {fast.stats.longestEmptyM > best.stats.longestEmptyM ? `, ${fast.stats.longestEmptyM - best.stats.longestEmptyM} m less of nothing open` : ''}. Scored live by the engine, not a picture.
                </p>
              </>
            ) : <p className="ticket__note">Scoring the corridor…</p>}
            <div className="ticket__stub" aria-hidden>
              <span className="mono">{plan?.planId ? `NO. ${plan.planId.slice(0, 8).toUpperCase()}` : 'NO. --------'}</span>
              <span className="ticket__code" />
            </div>
          </aside>
        </div>
      </header>

      <main className="lp-body">
        <div className="lp-col">
          <div className="lp-route">
          <section className="section lp-why">
            <p className="lp-quote">Map apps send you the fastest way. At 11:30 PM the fastest way is often the emptiest: the cafés that lit it at 6 PM are shut, and the map doesn't know.</p>
            <p className="lp-quote__after">HootRoute scores every block by what is listed open, lit and reachable at the minute you pass it, checks what it doesn't know, and brings in your people only if you stop and don't answer.</p>
          </section>

          <section className="section lp-split" id="how">
            <h2>How a walk goes</h2>
            <ol className="lp-steps">
              <li><b>Ask in plain words</b><span>"Leaving the library at 11:40, to Civic Center BART, fewer turns." Professor Hoot picks the tools.</span></li>
              <li><b>Compare real routes</b><span>Scoot scores every candidate at the minute you pass each block: open places, gaps, lighting, transit, turns.</span></li>
              <li><b>Investigate the unknown</b><span>Sherlock finds places with unknown hours and checks their listings, but only after you approve.</span></li>
              <li><b>Walk with a wingman</b><span>Wally follows the route. Report a block and get alternatives; nothing changes until you choose.</span></li>
            </ol>
          </section>

          <section className="section lp-split" id="crew">
            <h2>Who's walking with you</h2>
            <ul className="lp-crew">
              {CREW.map((id, i) => {
                const info = crew?.find((c) => c.id === id);
                return (
                  <li key={id}>
                    <Avatar id={id} state={stateOf(i)} size={40} />
                    <div className="lp-crew__who">
                      <b>{PERSONA[id]}</b>
                      {info && <span className={`lp-status ${info.live ? 'lp-status--on' : ''}`}>{info.live ? 'live' : 'not configured'}</span>}
                    </div>
                    <p>{info?.job ?? JOB[id].job}</p>
                    <small className="mono">{info?.runsOn ?? JOB[id].runsOn}</small>
                  </li>
                );
              })}
            </ul>
          </section>

          <section className="section lp-split">
            <h2>The fine print</h2>
            <ul className="lp-rules">{RULES.map((r) => <li key={r}>{r}.</li>)}</ul>
          </section>
          </div>

          <section className="section lp-close">
            <h2>Where to tonight?</h2>
            <p>Pick a start and a destination anywhere in San Francisco.</p>
            <Link className="btn btn--primary btn--lg" to="/plan">Plan a journey <Icon name="arrow" size={17} /></Link>
          </section>

          <footer className="landing__foot">
            <div className="landing__foot-main">
              <div className="landing__foot-brand"><Brand /><p>A walking companion for San Francisco late-shift workers.</p></div>
              <nav className="landing__foot-links" aria-label="Footer">
                <Link to="/plan">Plan a journey</Link>
                <a href="#how">How it works</a>
                <a href="#crew">The crew</a>
              </nav>
            </div>
            <div className="landing__foot-base"><span>Built at Cal Hacks 13.0</span><span>Conditions, not a safety rating. Never calls 911 for you.</span></div>
          </footer>
        </div>
      </main>
    </div>
  );
}
