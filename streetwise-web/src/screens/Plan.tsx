import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { BRAND } from '../lib/brand';
import { Link, useNavigate } from 'react-router-dom';
import PickerMap from '../components/PickerMap';
import { Button, Icon, Mascot } from '../components/ui';
import { inCity, LOCAL_DESTINATIONS, nameForPin, searchPlaces, type DestinationResult } from '../lib/search';
import { loadSettings, primeDemoData, saveSettings } from '../lib/store';
import { askHead, createPlan, createWalk, gpsMode, isLive, withFlags, type HeadAnswer, type Plan as LivePlan } from '../lib/api';
import { CheckerCard, HeadAnswerCard, HeadAsk } from '../components/AgentPanels';
import type { DemoData, LngLat } from '../lib/types';
import { minutesText } from '../lib/format';
import './walk.css';
import './plan.css';

type Field = 'from' | 'to';
interface Spot { name: string; lngLat: LngLat }
interface When { day: number; minute: number; label: string }

const DAY3 = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const MOSCONE: Spot = { name: 'Moscone Center', lngLat: [-122.4016, 37.7842] };

/** The current day (Mon = 0) and minute in San Francisco, whatever the phone's own time zone is. */
function sfNow() {
  const parts = new Intl.DateTimeFormat('en-US', { timeZone: 'America/Los_Angeles', weekday: 'short', hour: 'numeric', minute: 'numeric', hour12: false }).formatToParts(new Date());
  const get = (t: string) => parts.find((x) => x.type === t)?.value ?? '0';
  const day = Math.max(0, DAY3.indexOf(get('weekday')));
  const hour = Number(get('hour')) % 24;
  return { day, minute: hour * 60 + Number(get('minute')) };
}

function clock(minute: number) {
  const h = Math.floor(minute / 60) % 24;
  return `${h % 12 || 12}:${String(minute % 60).padStart(2, '0')} ${h < 12 ? 'AM' : 'PM'}`;
}

function whenOptions(): When[] {
  const { day, minute } = sfNow();
  const night = (d: number, m: number, short: string): When => ({ day: d % 7, minute: m % 1440, label: short });
  const now = Math.round(minute / 5) * 5;
  return [
    { day, minute: now >= 1440 ? 1435 : now, label: `Now · ${clock(now)}` },
    night(day, 22 * 60, `${DAY3[day]} 10 PM`),
    night(day, 23 * 60, `${DAY3[day]} 11 PM`),
    night(day + 1, 60, `${DAY3[(day + 1) % 7]} 1 AM`),
  ];
}

export default function Plan() {
  const nav = useNavigate();
  const saved = useMemo(loadSettings, []);
  const whens = useMemo(whenOptions, []);
  const [from, setFrom] = useState<Spot | null>(saved.origin ?? MOSCONE);
  const [to, setTo] = useState<Spot | null>(saved.destination ?? null);
  const [when, setWhen] = useState<When>(() => whens.find((w) => w.label === saved.depart?.label) ?? whens[2]);
  const [active, setActive] = useState<Field>(saved.destination ? 'from' : 'to');
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<DestinationResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [plan, setPlan] = useState<DemoData | LivePlan | null>(null);
  const [starting, setStarting] = useState(false);
  const [planning, setPlanning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pick, setPick] = useState<'fast' | 'best'>('best');
  const [sheetH, setSheetH] = useState(360);
  const sheet = useRef<HTMLElement>(null);
  const [headBusy, setHeadBusy] = useState(false);
  const [headAns, setHeadAns] = useState<HeadAnswer | null>(null);
  const headSession = useRef<string | null>(null);
  const preset = useRef<LivePlan | null>(null);   // a plan the Head already made: show it instead of planning again

  // keep the map clear of the sheet
  useEffect(() => {
    if (!sheet.current) return;
    const ro = new ResizeObserver(() => setSheetH(sheet.current?.getBoundingClientRect().height ?? 360));
    ro.observe(sheet.current);
    return () => ro.disconnect();
  }, []);

  // search: our own API first (works offline), Photon adds addresses
  useEffect(() => {
    const q = query.trim();
    if (q.length < 2) { setResults(LOCAL_DESTINATIONS.filter((d) => d.name.toLowerCase().includes(q.toLowerCase()))); setSearching(false); return; }
    const c = new AbortController();
    setSearching(true);
    const t = window.setTimeout(() => {
      searchPlaces(q, c.signal).then(setResults).catch(() => undefined).finally(() => { if (!c.signal.aborted) setSearching(false); });
    }, 160);
    return () => { window.clearTimeout(t); c.abort(); };
  }, [query]);

  const choose = useCallback((field: Field, spot: Spot) => {
    if (field === 'from') setFrom(spot); else setTo(spot);
    setQuery('');
    setResults([]);
    setPlan(null);
    setError(null);
    if (field === 'to' && !from) setActive('from');
  }, [from]);

  const onTap = useCallback(async (p: LngLat) => {
    if (!inCity(p)) { setError('That point is outside San Francisco.'); return; }
    const field = active;
    choose(field, { name: 'Dropped pin', lngLat: p });
    const name = await nameForPin(p);
    if (field === 'from') setFrom((cur) => (cur && cur.lngLat === p ? { ...cur, name } : cur)); else setTo((cur) => (cur && cur.lngLat === p ? { ...cur, name } : cur));
  }, [active, choose]);

  // score the route whenever the start, destination or time changes
  useEffect(() => {
    if (!from || !to) { setPlan(null); return; }
    if (preset.current) { const p = preset.current; preset.current = null; setPlan(p); setPick(p.recommended === 'fast' ? 'fast' : 'best'); setPlanning(false); return; }
    const c = new AbortController();
    setPlanning(true);
    setError(null);
    const t = window.setTimeout(() => {
      createPlan(from, to, { day: when.day, minute: when.minute }, c.signal)
        .then((d) => { setPlan(d); setPick(d.recommended === 'fast' ? 'fast' : 'best'); })
        .catch((e: Error) => { if (!c.signal.aborted) { setPlan(null); setError(e.message); } })
        .finally(() => { if (!c.signal.aborted) setPlanning(false); });
    }, 250);
    return () => { window.clearTimeout(t); c.abort(); };
  }, [from, to, when]);

  const ask = async (text: string) => {
    setHeadBusy(true); setError(null);
    try {
      const a = await askHead(text, headSession.current);
      headSession.current = a.session; setHeadAns(a);
      if (a.plan && a.planId && a.req) {
        preset.current = { ...a.plan, planId: a.planId };
        const { origin: o, destination: d, day, minute } = a.req;
        setQuery(''); setResults([]);
        setFrom({ name: o.name, lngLat: [o.lon, o.lat] }); setTo({ name: d.name, lngLat: [d.lon, d.lat] });
        setWhen(whens.find((w) => w.day === day && w.minute === minute) ?? { day, minute, label: `${DAY3[day]} ${clock(minute)}` });
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'The Head could not answer.');
    } finally { setHeadBusy(false); }
  };

  const useMyLocation = () => {
    if (!('geolocation' in navigator)) { setError('This browser cannot share a location.'); return; }
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        const p: LngLat = [pos.coords.longitude, pos.coords.latitude];
        if (!inCity(p)) { setError('You are outside San Francisco. Pick a start on the map.'); return; }
        choose('from', { name: 'My location', lngLat: p });
      },
      () => setError('Location is blocked. Search for a start or tap the map.'),
      { enableHighAccuracy: true, timeout: 8000 },
    );
  };

  const swap = () => { setFrom(to); setTo(from); setPlan(null); };
  const stats = plan?.stats;
  const gain = stats ? stats.streetwise.score - stats.shortest.score : 0;
  const extra = stats ? stats.streetwise.minutes - stats.shortest.minutes : 0;
  const same = !!plan && plan.options?.length === 1;

  const review = async () => {
    if (!from || !to || !plan) return;
    const next = { ...saved, origin: from, destination: to, depart: when };
    saveSettings(next);
    if (!isLive()) {
      primeDemoData(next, plan);
      nav(withFlags('/walk'));
      return;
    }
    setStarting(true);
    try {
      const replay = gpsMode() === 'replay';
      const w = await createWalk({
        planId: 'planId' in plan ? plan.planId : undefined, from, to, when: { day: when.day, minute: when.minute }, choice: pick === 'fast' ? 'usual' : 'streetwise',
        walker: saved.walkerName, guardian: saved.guardianName, guardianPhone: saved.guardianPhone, backupName: saved.backupName, backupPhone: saved.backupPhone, thresholds: saved.thresholds, replay, timeScale: replay ? saved.timeScale : 1,
      });
      nav(withFlags(w.walkPath));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not start the walk.');
      setStarting(false);
    }
  };

  const row = (field: Field, spot: Spot | null, placeholder: string) => (
    <div className={`plan__field${active === field ? ' on' : ''}`} onClick={() => { setActive(field); setQuery(''); }}>
      <span className={`plan__dot plan__dot--${field}`} aria-hidden />
      {active === field ? (
        <input
          autoFocus
          className="plan__input"
          value={query}
          placeholder={spot ? spot.name : placeholder}
          onChange={(e) => setQuery(e.target.value)}
          aria-label={field === 'from' ? 'Start' : 'Destination'}
        />
      ) : (
        <button type="button" className="plan__value" onClick={() => setActive(field)}>{spot ? spot.name : placeholder}</button>
      )}
    </div>
  );

  return (
    <div className="screen plan" data-theme="night">
      <PickerMap from={from?.lngLat ?? null} to={to?.lngLat ?? null} fast={plan?.shortest} best={plan?.route} highlight={pick} bottomPad={sheetH + 24} onTap={onTap} />

      <div className="plan__top">
        <Link to="/" className="round-btn" aria-label="Home"><Icon name="back" size={20} /></Link>
        <div className="chip"><span className="dot dot--live" />San Francisco · {when.label}</div>
      </div>

      <section className="sheet plan__sheet" ref={sheet} aria-label="Plan a walk">
        <div className="sheet__handle" aria-hidden />
        <div className="plan__head">
          <Mascot agent="guide" state={planning ? 'thinking' : plan ? 'done' : 'idle'} size={34} />
          <div className="t-headline" style={{ fontSize: 16 }}>{plan ? 'The Guide found your routes' : planning ? 'The Guide is scoring every block…' : 'Where are you walking?'}</div>
        </div>

        {isLive() && <HeadAsk busy={headBusy} onAsk={(t) => void ask(t)} />}
        {headAns && !query && <HeadAnswerCard a={headAns} />}

        <div className="plan__fields">
          {row('from', from, 'Start')}
          <button type="button" className="plan__swap" onClick={swap} aria-label="Swap start and destination"><Icon name="chevronDown" size={16} /></button>
          {row('to', to, 'Destination')}
        </div>
        {!query && !plan && !planning && <div className="t-caption">Or tap the map to drop the {active === 'from' ? 'start' : 'destination'} pin.</div>}

        {query.trim().length >= 0 && (results.length > 0 || searching) && (query || !to) && (
          <div className="plan__results" role="listbox">
            {active === 'from' && <button type="button" className="plan__result" onClick={useMyLocation}><span>Use my location<small>Asks your browser for permission</small></span></button>}
            {results.map((d) => (
              <button type="button" key={`${d.name}:${d.lngLat.join(',')}`} className="plan__result" onClick={() => choose(active, { name: d.name, lngLat: d.lngLat })}>
                <span>{d.name}<small>{d.detail}</small></span>
              </button>
            ))}
            {searching && <div className="t-caption plan__searching">Searching…</div>}
          </div>
        )}

        <div className="plan__when" role="radiogroup" aria-label="When are you leaving">
          {(whens.some((w) => w.label === when.label) ? whens : [...whens, when]).map((w) => (
            <button type="button" key={w.label} role="radio" aria-checked={when.label === w.label} className={`plan__chip${when.label === w.label ? ' on' : ''}`} onClick={() => setWhen(w)}>{w.label}</button>
          ))}
        </div>

        {error && <div className="plan__error" role="alert">{error}</div>}

        {plan && stats && !query && (
          <>
            <div className="plan__cards">
              <button type="button" className={`plan__card${pick === 'fast' ? ' on' : ''}`} onClick={() => setPick('fast')} aria-pressed={pick === 'fast'}>
                <div className="t-caption">{same ? 'Fastest · also best' : 'Fastest'}</div>
                <div className="plan__score">{stats.shortest.score}<small>/100</small></div>
                <div className="plan__meta">{minutesText(stats.shortest.minutes)}<br />{stats.shortest.longestEmptyM} m empty</div>
              </button>
              {!same && (
                <button type="button" className={`plan__card plan__card--best${pick === 'best' ? ' on' : ''}`} onClick={() => setPick('best')} aria-pressed={pick === 'best'}>
                  <div className="t-caption">{BRAND}</div>
                  <div className="plan__score">{stats.streetwise.score}<small>/100</small></div>
                  <div className="plan__meta">{minutesText(stats.streetwise.minutes)}<br />{stats.streetwise.longestEmptyM} m empty</div>
                </button>
              )}
            </div>
            <p className="plan__why">
              {same
                ? 'The fastest route is already the best one I found at this hour.'
                : `${BRAND} scores ${gain >= 0 ? '+' : ''}${gain} points higher for ${extra >= 0 ? '+' : ''}${extra.toFixed(1)} min. The longest stretch with nothing open drops from ${stats.shortest.longestEmptyM} m to ${stats.streetwise.longestEmptyM} m.`}
            </p>
            <div className="t-caption" style={{ fontSize: 11 }}>Compared with typical walks nearby at this hour. Conditions, not a safety rating.</div>
            <CheckerCard plan={plan} route={pick} onPlan={(p) => setPlan(p)} />
            <Button kind="primary" block disabled={starting} onClick={() => void review()}>{starting ? 'Starting your walk…' : 'Review this route'}</Button>
          </>
        )}
        {!plan && !planning && !error && from && to && <div className="t-caption">Scoring starts as soon as both pins are set.</div>}
      </section>
    </div>
  );
}
