import { TRAVEL_LABEL, defaultTravel } from './lib/travel';
import type { ModeConditions, TravelMode, TravelOptions, TravelSettings } from './lib/types';

function TravelOption({ label, checked, onChange }: { label: string; checked: boolean; onChange: (value: boolean) => void }) {
  return <label className="between small" style={{ minHeight: 44, cursor: 'pointer' }}>
    <span>{label}</span><input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} style={{ accentColor: 'var(--moon)', width: 18, height: 18 }} />
  </label>;
}

export function TravelControls({ value, onChange, disabled }: { value: TravelSettings; onChange: (v: TravelSettings) => void; disabled: boolean }) {
  const update = (key: keyof TravelOptions, next: number | boolean) => onChange({ ...value, options: { ...value.options, [key]: next } });
  return (
    <fieldset className="stack--tight" disabled={disabled} style={{ border: 0, padding: 0, margin: 0, minWidth: 0 }}>
      <legend className="eyebrow" style={{ marginBottom: 8 }}>How you travel</legend>
      <label className="field">
        <span className="sr">Travel mode</span>
        <select aria-label="Travel mode" value={value.mode} onChange={(e) => onChange(defaultTravel(e.target.value as TravelMode))}>
          {(Object.keys(TRAVEL_LABEL) as TravelMode[]).map((mode) => <option key={mode} value={mode}>{TRAVEL_LABEL[mode]}</option>)}
        </select>
      </label>
      {value.mode !== 'walk' && (
        <>
          <div className="row" style={{ alignItems: 'flex-start' }}>
            <label className="stack--tight" style={{ flex: 1, minWidth: 0 }}>
              <span className="small muted">Estimated pace</span>
              <span className="field"><select aria-label="Estimated pace" value={value.options.speedKmh} onChange={(e) => update('speedKmh', Number(e.target.value))}>
                {(value.mode === 'cycle' ? [10, 15, 20, 25] : [2, 3, 4, 5]).map((speed) => <option key={speed} value={speed}>{speed} km/h</option>)}
              </select></span>
            </label>
            {value.mode === 'wheelchair' && <label className="stack--tight" style={{ flex: 1, minWidth: 0 }}>
              <span className="small muted">Max mapped incline</span>
              <span className="field"><select aria-label="Maximum mapped incline" value={value.options.maxInclinePct} onChange={(e) => update('maxInclinePct', Number(e.target.value))}>
                {[3, 5, 8].map((slope) => <option key={slope} value={slope}>{slope}%</option>)}
              </select></span>
            </label>}
          </div>
          {value.mode === 'cycle' && <TravelOption label="Prefer mapped bike lanes" checked={!!value.options.preferCycleways} onChange={(on) => update('preferCycleways', on)} />}
          <TravelOption label="Avoid rough surfaces" checked={!!value.options.avoidRoughSurfaces} onChange={(on) => update('avoidRoughSurfaces', on)} />
          {value.mode === 'wheelchair' && <>
            <TravelOption label="Require wheelchair access tags" checked={!!value.options.requireKnownAccess} onChange={(on) => update('requireKnownAccess', on)} />
            <p className="p tiny">Mapped stairs and recorded access barriers are excluded. Missing sidewalk, kerb or incline information stays unknown. Requiring access tags can leave no connected route.</p>
          </>}
        </>
      )}
    </fieldset>
  );
}

export function TravelNotice({ mode = 'walk', options, conditions }: { mode?: TravelMode; options?: TravelOptions; conditions?: ModeConditions }) {
  if (mode === 'walk') return null;
  return <div className={`card stack--tight ${mode === 'wheelchair' ? 'card--amber' : ''}`}>
    <span className="small" style={{ fontWeight: 600 }}>{TRAVEL_LABEL[mode]} · estimated {options?.speedKmh ?? (mode === 'cycle' ? 15 : 3)} km/h</span>
    {mode === 'cycle'
      ? <p className="p small">Mapped bike lanes or cycleways on {conditions?.cyclewayPct ?? 0}% of this route. Bicycle access and one-way restrictions are applied.</p>
      : <p className="p small">Wheelchair access tags are missing on {100 - (conditions?.wheelchairTagsPct ?? 0)}% of this route. Surface unknown: {conditions?.unknownSurfacePct ?? 100}%; measured incline unknown: {conditions?.unknownInclinePct ?? 100}%. Check sidewalks, kerbs and entrances before travelling.</p>}
    <span className="faint tiny">Access between your chosen place and the mapped route is unverified. Conditions, not a safety rating.</span>
  </div>;
}
