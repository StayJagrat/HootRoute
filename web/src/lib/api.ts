import type { DemoData, LngLat, Thresholds } from './types';
import { BRAND } from './brand';

// Two independent switches (URL first, then build env, then the production default):
//   ?agents=live|demo  live = the gateway's agents drive the walk; demo = the local DemoEngine plays them from cached data
//   ?gps=real|replay   real = the phone's GPS; replay = positions replayed along the route (badged "DEMO · GPS REPLAY")
// The stage demo indoors is ?gps=replay with live agents: real agents answering a replayed walk.

const query = () => new URLSearchParams(location.search);

export type AgentsMode = 'live' | 'demo';
export type GpsMode = 'real' | 'replay';

export function agentsMode(): AgentsMode {
  const q = query();
  const v = q.get('agents') ?? (q.get('engine') === 'off' ? 'live' : q.get('engine') === 'on' ? 'demo' : null) ?? (import.meta.env.VITE_AGENTS as string | undefined);
  return v === 'demo' ? 'demo' : 'live';
}

export function gpsMode(): GpsMode {
  const v = query().get('gps') ?? (import.meta.env.VITE_GPS as string | undefined);
  return v === 'replay' ? 'replay' : 'real';
}

export const isLive = () => agentsMode() === 'live';

/** Carry ?agents / ?gps / ?admin to the next screen. */
export function withFlags(path: string): string {
  const keep = new URLSearchParams();
  for (const k of ['agents', 'gps', 'engine']) { const v = query().get(k); if (v) keep.set(k, v); }
  if (![...keep.keys()].length) return path;
  return `${path}${path.includes('?') ? '&' : '?'}${keep}`;
}

// ---------------------------------------------------------------- credentials
// The walker's phone holds the walk's walker token; the control room may hold an admin token.
interface WalkCreds { token: string; guardianUrl: string; created: number }

export function saveWalkCreds(walkId: string, creds: WalkCreds) {
  try {
    localStorage.setItem(`hootroute:walk:${walkId}`, JSON.stringify(creds));
    localStorage.setItem('hootroute:lastWalk', walkId);
  } catch {
    /* storage blocked */
  }
}
export function walkCreds(walkId: string): WalkCreds | null {
  const q = query();      // a walker link from the ASI:One chat carries the token once (?walk=…&t=…)
  if (q.get('walk') === walkId && q.get('t')) { saveWalkCreds(walkId, { token: q.get('t')!, guardianUrl: `${location.origin}/guardian/${walkId}`, created: Date.now() }); }
  try {
    const raw = localStorage.getItem(`hootroute:walk:${walkId}`);
    return raw ? (JSON.parse(raw) as WalkCreds) : null;
  } catch {
    return null;
  }
}
export function lastWalkId(): string | null {
  try {
    return localStorage.getItem('hootroute:lastWalk');
  } catch {
    return null;
  }
}
export function adminToken(): string {
  const q = query().get('admin');
  try {
    if (q) localStorage.setItem('hootroute:admin', q);
    return q ?? localStorage.getItem('hootroute:admin') ?? '';
  } catch {
    return q ?? '';
  }
}

// ---------------------------------------------------------------- REST
async function call<T>(path: string, init?: RequestInit): Promise<T> {
  let r: Response;
  try {
    r = await fetch(path, { ...init, headers: { 'Content-Type': 'application/json', ...(adminToken() ? { 'X-Admin-Token': adminToken() } : {}), ...(init?.headers ?? {}) } });
  } catch {
    throw new Error(`Cannot reach ${BRAND}. Check your connection and try again.`);
  }
  if (!r.ok) {
    const body = (await r.json().catch(() => ({}))) as { detail?: string | { msg: string }[] };
    const detail = Array.isArray(body.detail) ? body.detail.map((d) => d.msg).join(' ') : body.detail;
    throw new Error(detail ?? `${BRAND} answered ${r.status}.`);
  }
  return r.json() as Promise<T>;
}

export interface Spot { name: string; lngLat: LngLat }
const point = (s: Spot) => ({ lat: s.lngLat[1], lon: s.lngLat[0], name: s.name });

export type Plan = DemoData & { planId: string };

export function createPlan(from: Spot, to: Spot, when: { day: number; minute: number } | null, signal?: AbortSignal) {
  return call<Plan>('/api/plans', { method: 'POST', signal, body: JSON.stringify({ origin: point(from), destination: point(to), day: when?.day ?? null, minute: when?.minute ?? null }) });
}

export interface NewWalk { walkId: string; walkerToken: string; guardianUrl: string; walkPath: string; sms: boolean }

export async function createWalk(p: {
  planId?: string; from: Spot; to: Spot; when: { day: number; minute: number } | null; choice: 'hootroute' | 'usual';
  walker: string; guardian: string; guardianPhone?: string; backupName?: string; backupPhone?: string; thresholds: Thresholds; replay: boolean; timeScale: number;
}): Promise<NewWalk> {
  const w = await call<NewWalk>('/api/walks', {
    method: 'POST',
    body: JSON.stringify({
      planId: p.planId, origin: point(p.from), destination: point(p.to), day: p.when?.day ?? null, minute: p.when?.minute ?? null, choice: p.choice,
      walker: p.walker || 'Walker', guardian: p.guardian || 'Guardian', guardianPhone: p.guardianPhone || null, backupName: p.backupName || null, backupPhone: p.backupPhone || null, thresholds: p.thresholds, replay: p.replay, timeScale: p.timeScale,
    }),
  });
  saveWalkCreds(w.walkId, { token: w.walkerToken, guardianUrl: w.guardianUrl, created: Date.now() });
  return w;
}

export interface WalkSummary { id: string; status: string; walker_name: string; guardian_name: string; created_at: number; replay: boolean }
export const listWalks = (active = true) => call<WalkSummary[]>(`/api/walks?active=${active}&limit=10`);

export interface PlaceInfo {
  id: string; name: string; cat: string; lngLat: LngLat; listedHours: string | null; hoursSource: string | null;
  declaration: { openUntil: string; safeHaven: boolean; frontLight: boolean; updatedAt: number } | null; walksNearby: number;
}
export const placeInfo = (id: string) => call<PlaceInfo>(`/api/places/${encodeURIComponent(id)}`);
export const declareHours = (id: string, d: { openUntil: string; safeHaven: boolean; frontLight: boolean }) =>
  call<{ ok: boolean; walksNotified: number }>(`/api/places/${encodeURIComponent(id)}/declaration`, { method: 'POST', body: JSON.stringify(d) });

export interface Health { ok: boolean; tts: 'cartesia' | 'device'; sms: boolean; runtime: string; claude?: boolean; apify?: boolean }

// ---------------------------------------------------------------- the Head (Claude) and the Checker
export interface TraceStep { agent: 'head' | 'guide' | 'checker'; tool: string; input: unknown; ok: boolean; ms: number; summary: string }
export interface UnknownPlace { id: string; name: string; cat: string; lngLat: LngLat; atM: number; passMinute: number }
export interface HoursResult { id: string; name: string; status: 'hours found' | 'no hours' | 'closed' | 'not found' | 'check failed'; hours: string | null; source?: string | null; listingName?: string; checkedAt?: string }
export interface CheckRun { ok: boolean; results: HoursResult[]; note: string; changed: number; mock?: boolean; run?: { actor: string; seconds: number; items: number } | null }
export interface HeadAnswer {
  session: string; answer: string; by: string; trace: TraceStep[]; ms: number; planId?: string; plan?: DemoData;
  before?: DemoData['stats']; after?: DemoData['stats']; routeChanged?: boolean; unknowns?: UnknownPlace[]; check?: CheckRun;
  req?: { origin: { name: string; lat: number; lon: number }; destination: { name: string; lat: number; lon: number }; day: number; minute: number };
}
export const askHead = (text: string, session?: string | null, allowChecks = true, signal?: AbortSignal) =>
  call<HeadAnswer>('/api/head/ask', { method: 'POST', signal, body: JSON.stringify({ text, session: session ?? null, allowChecks }) });
export interface Inspection {
  verdict: string; good: boolean; score: number; minutes: number; arrive: string; route: 'best' | 'fast'; note: string; missing: string[];
  items: { level: 'ok' | 'note' | 'warn'; title: string; detail: string; source: string }[];
}
export const inspectRoute = (planId: string, route: 'best' | 'fast' = 'best') =>
  call<Inspection>('/api/check/route', { method: 'POST', body: JSON.stringify({ planId, route }) });
export const routeUnknowns = (planId: string) =>
  call<{ places: UnknownPlace[]; total: number | null; apify: boolean }>('/api/check/unknowns', { method: 'POST', body: JSON.stringify({ planId }) });
export const checkHours = (planId: string, placeIds?: string[]) =>
  call<CheckRun & { before: DemoData['stats']; after: DemoData['stats']; routeChanged: boolean; planId: string; plan: Plan }>('/api/check/hours', { method: 'POST', body: JSON.stringify({ planId, placeIds }) });
export const health = () => call<Health>('/api/health');
