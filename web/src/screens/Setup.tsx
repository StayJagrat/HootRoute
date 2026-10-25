import { useState } from 'react';
import { BRAND } from '../lib/brand';
import { useNavigate } from 'react-router-dom';
import { Button, Icon, Initials, Mascot } from '../components/ui';
import { loadSettings, saveSettings } from '../lib/store';
import type { AgentName } from '../lib/types';
import { PERSONA } from '../lib/personas';
import './setup.css';

const CREW: [AgentName, string, string][] = [
  ['head', PERSONA.head, 'reads your request, picks the tools, asks before any paid check and explains every choice'],
  ['guide', PERSONA.guide, 'plans and scores the route at the minute you pass each block, and re-plans around obstacles'],
  ['checker', PERSONA.checker, 'finds unknown hours on the route and checks published listings after you approve'],
  ['rescuer', PERSONA.rescuer, 'handles the live walk: obstacle reports, route recovery, sharing on and off, and check-ins'],
];

export default function Setup() {
  const nav = useNavigate();
  const [s, setS] = useState(loadSettings);
  const [picked, setPicked] = useState<AgentName>('head');
  const set = (patch: Partial<typeof s>) => setS({ ...s, ...patch });
  const setT = (k: keyof typeof s.thresholds, v: number) => setS({ ...s, thresholds: { ...s.thresholds, [k]: v } });

  return (
    <div className="screen screen--scroll setup" data-theme="night">
      <main className="setup__body">
        <h1 className="t-display" style={{ fontSize: 32, lineHeight: '36px' }}>Before your first walk</h1>

        <section className="card setup__crew">
          <div className="t-caption">Meet the crew — four agents that walk with you</div>
          <div className="setup__crew-row">
            {CREW.map(([a, name]) => (
              <button type="button" key={a} className={`setup__crew-item${picked === a ? ' on' : ''}`} onClick={() => setPicked(a)} aria-pressed={picked === a}>
                <Mascot agent={a} state={picked === a ? 'talking' : 'idle'} size={54} />
                <span className="setup__crew-name">{name}</span>
              </button>
            ))}
          </div>
          <p className="setup__crew-line">{CREW.find((c) => c[0] === picked)?.[1]} {CREW.find((c) => c[0] === picked)?.[2]}.</p>
        </section>

        <section className="card setup__guardian">
          <Initials text={s.guardianName[0] ?? 'G'} size={42} />
          <div style={{ flex: 1 }}>
            <div className="t-caption" style={{ fontSize: 12 }}>Guardian</div>
            <input className="setup__input" value={s.guardianName} onChange={(e) => set({ guardianName: e.target.value })} aria-label="Guardian name" />
            <input className="setup__input setup__input--phone" type="tel" inputMode="tel" autoComplete="tel" placeholder="Phone for text and call (optional)"
              value={s.guardianPhone ?? ''} onChange={(e) => set({ guardianPhone: e.target.value })} aria-label="Guardian phone" />
            <div className="t-caption" style={{ fontSize: 12 }}>Gets a live link only during a walk · a text or call only if you opt in below</div>
          </div>
        </section>

        <section className="card setup__guardian">
          <Initials text={s.backupName?.[0] ?? '+'} size={42} />
          <div style={{ flex: 1 }}>
            <div className="t-caption" style={{ fontSize: 12 }}>Backup contact (optional)</div>
            <input className="setup__input" value={s.backupName ?? ''} placeholder="Name" onChange={(e) => set({ backupName: e.target.value })} aria-label="Backup contact name" />
            <input className="setup__input setup__input--phone" type="tel" inputMode="tel" autoComplete="tel" placeholder="Phone for text and call"
              value={s.backupPhone ?? ''} onChange={(e) => set({ backupPhone: e.target.value })} aria-label="Backup contact phone" />
            <div className="t-caption" style={{ fontSize: 12 }}>Only if your guardian doesn't answer and you opt in below: step 3 of the rescue ladder</div>
          </div>
        </section>

        <label className="card setup__consent">
          <input type="checkbox" checked={!!s.notifyConsent} onChange={(e) => set({ notifyConsent: e.target.checked })} />
          <span>
            <span className="t-headline" style={{ fontSize: 15 }}>Text or call my contacts if I don't answer a check-in</span>
            <span className="t-caption" style={{ fontSize: 12, display: 'block' }}>Off by default. Without it, {BRAND} only uses the live link you share; no text or call is ever sent.</span>
          </span>
        </label>

        <section className="card setup__orders">
          <div className="t-number muted" style={{ fontSize: 13, letterSpacing: 1.2 }}>STANDING ORDERS</div>
          <p className="setup__sentence">
            If I stop on a dim stretch for{' '}
            <Pick value={s.thresholds.stopSeconds} options={[60, 90, 120]} suffix=" s" tone="checkin" onChange={(v) => setT('stopSeconds', v)} /> and don't answer in{' '}
            <Pick value={s.thresholds.replySeconds} options={[30, 45, 60]} suffix=" s" tone="checkin" onChange={(v) => setT('replySeconds', v)} />, send{' '}
            <span className="pick pick--route">{s.guardianName.split(' ')[0] || 'my guardian'}</span> my live location{s.notifyConsent ? ', then text and call' : ' on the live link'}.
          </p>
        </section>

        <section className="setup__note">
          <Icon name="phoneOff" size={24} />
          <div>
            <div className="t-headline" style={{ fontSize: 15 }}>{BRAND} never calls 911 for you.</div>
            <div className="t-caption" style={{ fontSize: 12 }}>Mic is on only during a walk. Audio isn't stored.</div>
          </div>
        </section>

        <label className="setup__demo t-caption">
          GPS replay speed (indoor demos only)
          <select value={s.timeScale} onChange={(e) => set({ timeScale: Number(e.target.value) })}>
            {[1, 3, 6, 10].map((v) => <option key={v} value={v}>×{v}</option>)}
          </select>
        </label>

        <Button kind="primary" block onClick={() => {
          saveSettings(s);
          nav('/plan');
        }}>Save · plan a walk</Button>
      </main>
    </div>
  );
}

function Pick({ value, options, suffix, tone, onChange }: { value: number; options: number[]; suffix: string; tone: 'checkin' | 'route'; onChange: (v: number) => void }) {
  return (
    <label className={`pick pick--${tone}`}>
      <select value={value} onChange={(e) => onChange(Number(e.target.value))}>
        {options.map((o) => <option key={o} value={o}>{o}{suffix}</option>)}
      </select>
      {value}{suffix}
      <Icon name="chevronDown" size={12} />
    </label>
  );
}
