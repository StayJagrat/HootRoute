import { useMemo } from 'react';
import { useParams } from 'react-router-dom';
import { useWalk } from '../lib/store';
import { MapCanvas } from '../Map';
import { Brand, Icon } from '../ui';

/** The trusted contact's view: opened from the walker's link (?g=<token>). Read-only except "I'm on it". */
export default function Guardian() {
  const { walk = '' } = useParams();
  const { state, send, refused } = useWalk(walk, 'guardian');
  const data = state.plan?.data;
  const line = useMemo(() => (data ? (state.choice === 'usual' ? data.shortest : data.route) : []), [data, state.choice]);
  const stopped = refused === 4401 || state.sharing === false;
  const narrow = typeof window !== 'undefined' && window.innerWidth <= 760;
  const walker = state.plan?.walker ?? 'Your contact';

  return (
    <div className="app">
      {!stopped && <MapCanvas routes={line.length ? [{ id: 'r', coords: line, active: true }] : []} start={line[0]} end={line.at(-1)} puck={state.position?.lngLat}
        fitKey={String(line.length)} follow pad={narrow ? { left: 0, bottom: window.innerHeight * 0.45 } : { left: 420, bottom: 0 }} />}
      <section className="panel" aria-label="Shared journey">
        <header className="panel__head"><Brand sub="shared journey" /></header>
        <div className="panel__body">
          {stopped ? (
            <div className="stack" style={{ marginTop: 8 }}>
              <h1 className="h1">Sharing was stopped.</h1>
              <p className="p">The walker turned off location sharing or this link was replaced. You can't see their position from this link anymore.</p>
            </div>
          ) : !data ? (
            <p className="p" style={{ marginTop: 8 }}>Connecting to the journey…</p>
          ) : (
            <>
              <div className="stack--tight" style={{ marginTop: 8 }}>
                <span className="eyebrow">{state.phase === 'arrived' ? 'Arrived' : state.phase === 'preview' ? 'Not started yet' : 'Walking now'}</span>
                <h1 className="h1">{walker} → {data.end.name}</h1>
                <p className="p small">From {data.start.name}. Live position appears on the map while they walk.</p>
              </div>
              {state.alert && (
                <div className="card card--red stack fade" role="alert">
                  <span className="row" style={{ color: 'var(--red)', fontWeight: 600 }}><Icon name="alert" size={18} /> No answer to a check-in</span>
                  <p style={{ margin: 0 }}>{state.alert.reason}. Last seen on {state.alert.where}.</p>
                  {state.alert.ackBy
                    ? <span className="badge badge--mint" style={{ alignSelf: 'flex-start' }}>{state.alert.ackBy} is on it</span>
                    : <button className="btn btn--primary" onClick={() => send({ type: 'guardian.ack', by: 'Contact' })}>I'm on it</button>}
                  <a className="btn btn--danger" href="tel:911">Call 911 if you think it's an emergency</a>
                  <span className="faint tiny">HootRoute never calls 911. Only a person can.</span>
                </div>
              )}
              {state.phase === 'arrived' && state.summary && <p className="p" style={{ color: 'var(--fg)' }}>{state.summary}</p>}
            </>
          )}
        </div>
      </section>
    </div>
  );
}
