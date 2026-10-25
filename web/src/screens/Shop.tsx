import { useEffect, useMemo, useState } from 'react';
import { PERSONA } from '../lib/personas';
import { useParams } from 'react-router-dom';
import { Mascot, Toggle } from '../components/ui';
import { clock } from '../lib/format';
import { loadSettings, mergedPlaces, useDemoData, useWalk, walkIdFromUrl } from '../lib/store';
import { declareHours, isLive, placeInfo, type PlaceInfo } from '../lib/api';
import type { Place } from '../lib/types';
import './shop.css';

// The demo shopkeeper updates listed hours, a place to pause, and front light.

const TIMES = ['22:00', '22:30', '23:00', '23:30', '00:00', '00:30', '01:00', '01:30', '02:00', '03:00', '04:00'];

export default function Shop() {
  const { place: routePlace } = useParams();
  const live = isLive();
  const walkId = walkIdFromUrl() || 'demo';
  const { data, error: demoError } = useDemoData(!live);
  const placeId = routePlace ?? data?.whatIf?.placeId ?? data?.places[0]?.id ?? '';
  const settings = useMemo(loadSettings, []);
  const { state, send, status } = useWalk(live ? 'demo' : walkId, 'shop');
  const [toast, setToast] = useState<number | null>(null);
  const [info, setInfo] = useState<PlaceInfo | null>(null);
  const [liveError, setLiveError] = useState<string | null>(null);
  const [notified, setNotified] = useState(0);

  // live: the shop page talks to the city, not to one walk
  useEffect(() => {
    if (!live || !placeId) return;
    placeInfo(placeId).then(setInfo, (e: Error) => setLiveError(e.message));
  }, [live, placeId]);
  const livePlace: Place | undefined = info ? {
    id: info.id, name: info.name, kind: info.cat === 'pharmacy' ? 'pharmacy' : 'cafe', lngLat: info.lngLat, simulated: false,
    openUntil: info.declaration?.openUntil ?? 'closed', safeHaven: info.declaration?.safeHaven ?? false, frontLight: info.declaration?.frontLight ?? true,
    address: info.listedHours ? `Listed hours: ${info.listedHours}` : 'No listed hours on record',
  } : undefined;
  const place = live ? livePlace : data ? mergedPlaces(data, state).find((p) => p.id === placeId) : undefined;
  const error = live ? liveError : demoError;
  const [open, setOpen] = useState(true);
  const [until, setUntil] = useState('01:00');
  const [haven, setHaven] = useState(true);
  const [light, setLight] = useState(true);

  useEffect(() => {
    if (!place) return;
    setOpen(place.openUntil !== 'closed');
    if (place.openUntil !== 'closed' && /\d/.test(place.openUntil)) setUntil(place.openUntil);
    setHaven(place.safeHaven);
    setLight(place.frontLight ?? true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [place?.id]);

  const publish = (next: { open?: boolean; until?: string; haven?: boolean; light?: boolean }) => {
    const o = next.open ?? open, u = next.until ?? until, h = next.haven ?? haven, l = next.light ?? light;
    const decl = { openUntil: o ? u : 'closed', safeHaven: o && h, frontLight: l };
    if (live) {
      declareHours(placeId, decl).then((r) => { setNotified(r.walksNotified); if (o) setToast(Date.now()); }, (e: Error) => setLiveError(e.message));
      return;
    }
    send({ type: 'place.update', place: { id: placeId, ...decl } });
    if (o) setToast(Date.now());
  };

  useEffect(() => {
    if (!toast) return;
    const t = window.setTimeout(() => setToast(null), 6000);
    return () => window.clearTimeout(t);
  }, [toast]);

  if (live && !placeId) return <div className="screen" data-theme="day" style={{ padding: 24 }}>Open your shop's own link (/shop/&lt;place id&gt;).</div>;
  if (!live && !data) return <div className="screen" data-theme="day" role={error ? 'alert' : undefined} style={{ padding: 24 }}>{error ?? 'Loading route…'}</div>;
  if (!place) return <div className="screen" data-theme="day" role={error ? 'alert' : undefined} style={{ padding: 24 }}>{error ?? (live ? 'Loading your shop…' : `Unknown place “${placeId}”.`)}</div>;

  const idx = Math.max(0, TIMES.indexOf(until));
  const walking = live ? notified > 0 : state.phase === 'walking' || state.phase === 'checkin' || state.phase === 'escalated';

  return (
    <div className="screen screen--scroll shop" data-theme="day">
      <Storefront open={open} />
      <main className="shop__body">
        <div className="shop__head">
          <div>
            <h1 className="t-display">{place.name}</h1>
            <div className="t-caption">{place.address ?? 'Downtown SF'}</div>
          </div>
          {place.simulated ? <span className="tag-sim">Simulated</span> : (
            <span className={`agent-pill agent-pill--${live ? (info ? "online" : "connecting") : status}`}><span className="dot" /> Place agent live</span>
          )}
        </div>

        <section className="card shop__open">
          <div className="shop__open-text">
            <h2 className="t-title">{open ? 'Staying open late' : 'Closed for the night'}</h2>
            <p className="t-caption" style={{ margin: 0 }}>{open ? 'Walkers nearby see your updated hours when they pass your door.' : 'Turn on staying open to share updated hours with walkers nearby.'}</p>
            <div className={`stepper${open ? '' : ' stepper--off'}`}>
              <button type="button" aria-label="Earlier" onClick={() => { const u = TIMES[Math.max(0, idx - 1)]; setUntil(u); publish({ until: u }); }} disabled={!open}>–</button>
              <div>
                <div className="t-caption" style={{ fontSize: 11 }}>until</div>
                <div className="t-number" style={{ fontSize: 22, lineHeight: '22px' }}>{clock(until).toUpperCase()}</div>
              </div>
              <button type="button" aria-label="Later" onClick={() => { const u = TIMES[Math.min(TIMES.length - 1, idx + 1)]; setUntil(u); publish({ until: u }); }} disabled={!open}>+</button>
            </div>
          </div>
          <button type="button" role="switch" aria-checked={open} aria-label="Staying open" className={`rocker${open ? ' rocker--on' : ''}`} onClick={() => { setOpen(!open); publish({ open: !open }); }}>
            <span className="rocker__plate"><span className="rocker__label t-number">{open ? 'ON' : 'OFF'}</span></span>
          </button>
        </section>

        <section className="card shop__list">
          <div className="shop__row">
            <div>
              <div className="t-headline">Place to pause</div>
              <div className="t-caption">Walkers can wait inside if they need to</div>
            </div>
            <Toggle on={haven && open} label="Place to pause" onChange={(v) => { setHaven(v); publish({ haven: v }); }} />
          </div>
          <div className="shop__row">
            <div>
              <div className="t-headline">Front light on</div>
              <div className="t-caption">Shown to walkers; this is not part of the score</div>
            </div>
            <Toggle on={light} label="Front light on" onChange={(v) => { setLight(v); publish({ light: v }); }} />
          </div>
        </section>

        {toast && (
          <div className="shop__toast" role="status">
            <Mascot agent="guide" state="done" size={48} />
            <div>
              <div className="t-headline" style={{ fontSize: 15 }}>Your hours update is visible to nearby walkers.</div>
              <div className="shop__toast-sub">{live ? (notified ? `${PERSONA.guide} told ${notified} walk${notified === 1 ? '' : 's'} passing your door · just now` : `${PERSONA.guide} will offer it to the next walker · just now`) : walking ? `Simulated · ${PERSONA.guide} kept ${settings.walkerName}'s walk past your door · just now` : `${PERSONA.guide} will offer it to the next walker · just now`}</div>
            </div>
          </div>
        )}
        <p className="t-caption" style={{ textAlign: 'center', margin: '4px 0 0' }}>Your hours are shared with nearby walkers only while you're open.</p>
      </main>
    </div>
  );
}

function Storefront({ open }: { open: boolean }) {
  const stripes = Array.from({ length: 9 }, (_, i) => i);
  const w = 393 / 9;
  return (
    <div className="storefront" aria-hidden>
      <svg viewBox="0 0 393 250" preserveAspectRatio="xMidYMid slice">
        <rect width="393" height="250" fill="#2B2F38" />
        <rect x="40" y="132" width="313" height="118" fill="#3A3F4B" />
        <rect x="58" y="150" width="150" height="100" rx="4" fill={open ? '#F6D9A8' : '#4A5060'} fillOpacity={open ? 0.85 : 1} />
        <rect x="226" y="150" width="108" height="100" rx="4" fill={open ? '#F6D9A8' : '#4A5060'} fillOpacity={open ? 0.6 : 1} />
        <rect x="232" y="196" width="6" height="12" rx="3" fill="#2B2F38" />
        {open && <path d="M70 210 h50 v40 h-50 Z" fill="#C98F4E" fillOpacity="0.5" />}
        {stripes.map((i) => (
          <path key={i} d={`M${i * w} 60 h${w} v54 a${w / 2} ${(w / 2) * 0.55} 0 0 1 -${w} 0 Z`} fill={i % 2 ? '#F4F0E8' : '#1F5C46'} />
        ))}
        <rect x="0" y="52" width="393" height="10" fill="#174636" />
      </svg>
    </div>
  );
}
