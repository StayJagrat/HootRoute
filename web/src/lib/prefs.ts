import type { Preferences } from './api';

// Route preferences live on this device only. Sent to Scoot McRoute with every plan.
export const NO_PREFS: Preferences = { fewerTurns: false, preferOpenPlaces: false, preferMainRoads: false, fastest: false, lowDistraction: false };
const KEY = 'hootroute:prefs';

export function loadPrefs(): Preferences {
  try {
    const raw = localStorage.getItem(KEY);
    if (raw) return { ...NO_PREFS, ...(JSON.parse(raw) as Partial<Preferences>) };
  } catch {
    /* storage blocked */
  }
  return NO_PREFS;
}
export function savePrefs(p: Preferences) {
  try {
    localStorage.setItem(KEY, JSON.stringify(p));
  } catch {
    /* storage blocked */
  }
}
export const anyPrefs = (p: Preferences) => p.fewerTurns || p.preferOpenPlaces || p.preferMainRoads || p.fastest || p.lowDistraction;

export const PREF_LABEL: Record<Exclude<keyof Preferences, 'notes'>, string> = {
  fewerTurns: 'Fewer turns',
  preferOpenPlaces: 'Listed-open places',
  preferMainRoads: 'Main roads',
  fastest: 'Fastest',
  lowDistraction: 'Low-distraction guidance',
};
