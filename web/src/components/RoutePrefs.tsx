import type { Preferences } from '../lib/api';
import { PREF_LABEL } from '../lib/prefs';

const ORDER: (keyof typeof PREF_LABEL)[] = ['fewerTurns', 'preferOpenPlaces', 'preferMainRoads', 'fastest', 'lowDistraction'];

/** What matters on this walk. Sent to Scoot McRoute with the plan; low-distraction also changes the walk screen. */
export function RoutePrefs({ value, onChange }: { value: Preferences; onChange: (p: Preferences) => void }) {
  return (
    <div className="prefs" role="group" aria-label="Route preferences">
      <div className="prefs__row">
        {ORDER.map((k) => (
          <button type="button" key={k} className={`pref-chip${value[k] ? ' pref-chip--on' : ''}`} aria-pressed={!!value[k]} onClick={() => onChange({ ...value, [k]: !value[k] })}>
            {PREF_LABEL[k]}
          </button>
        ))}
      </div>
      {value.lowDistraction && <p className="prefs__why">Low-distraction: on the walk you hear turn prompts and check-ins only, and the screen shows less.</p>}
    </div>
  );
}
