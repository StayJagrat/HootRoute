import type { AgentName, DemoData, LngLat, RouteStats, Thresholds } from './types';
import { BRAND } from './brand';

// Every screen talks to the live gateway agents. One switch for indoor demos:
//   ?gps=real|replay   real = the phone's GPS; replay = positions replayed along the route (labelled "GPS replay · demo")

const query = () => new URLSearchParams(location.search);

export type AgentsMode = 'live' | 'demo';
export type GpsMode = 'real' | 'replay';

/** The scripted offline demo engine was removed: agents are always the gateway's. */
export function agentsMode(): AgentsMode {
  return 'live';
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
interface WalkCreds { token: string; guardianUrl: string | null; created: number; choice?: WalkChoice; sharing?: boolean }

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
  let saved: WalkCreds | null = null;
  try {
    const raw = localStorage.getItem(`hootroute:walk:${walkId}`);
    saved = raw ? (JSON.parse(raw) as WalkCreds) : null;
  } catch {
    saved = null;
  }
  if (q.get('walk') === walkId && q.get('t') && saved?.token !== q.get('t')) {
    // the guardian link carries its own token, which this walker link doesn't include
    saved = { token: q.get('t')!, guardianUrl: null, created: Date.now() };
    saveWalkCreds(walkId, saved);
  }
  return saved;
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
  if (r.status === 429) {
    const wait = Number(r.headers.get('Retry-After'));
    throw new ApiError(429, Number.isFinite(wait) && wait > 0
      ? `Too many requests right now. Try again in ${Math.ceil(wait)} s.`
      : 'Too many requests right now, or the daily limit for paid checks is used up. Try again in a minute.');
  }
  if (!r.ok) {
    const body = (await r.json().catch(() => ({}))) as { detail?: string | { msg: string }[] };
    const detail = Array.isArray(body.detail) ? body.detail.map((d) => d.msg).join(' ') : body.detail;
    throw new ApiError(r.status, detail ?? `${BRAND} answered ${r.status}.`);
  }
  return r.json() as Promise<T>;
}

/** An HTTP error with its status, so screens can tell "expired" (404) from "slow down" (429). */
export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) { super(message); this.status = status; }
}
export const errorText = (e: unknown, fallback: string) => (e instanceof Error && e.message ? e.message : fallback);

export interface Spot { name: string; lngLat: LngLat }
const point = (s: Spot) => ({ lat: s.lngLat[1], lon: s.lngLat[0], name: s.name });

export interface Preferences { fewerTurns: boolean; preferOpenPlaces: boolean; preferMainRoads: boolean; fastest: boolean; lowDistraction: boolean; notes?: string }
export interface PreferenceChoice { optionId: 'fast' | 'balanced' | 'best'; reason: string }
export type Plan = DemoData & { planId: string; preferenceChoice?: PreferenceChoice | null };
export type WalkChoice = 'hootroute' | 'usual' | 'balanced';

export function createPlan(from: Spot, to: Spot, when: { day: number; minute: number } | null, signal?: AbortSignal, preferences?: Partial<Preferences>) {
  return call<Plan>('/api/plans', { method: 'POST', signal, body: JSON.stringify({ origin: point(from), destination: point(to), day: when?.day ?? null, minute: when?.minute ?? null, ...(preferences ? { preferences } : {}) }) });
}

export interface NewWalk { walkId: string; walkerToken: string; guardianUrl: string; walkPath: string; sms: boolean }

export async function createWalk(p: {
  planId?: string; from: Spot; to: Spot; when: { day: number; minute: number } | null; choice: WalkChoice; notifyConsent?: boolean;
  walker: string; guardian: string; guardianPhone?: string; backupName?: string; backupPhone?: string; thresholds: Thresholds; replay: boolean; timeScale: number;
}): Promise<NewWalk> {
  const w = await call<NewWalk>('/api/walks', {
    method: 'POST',
    body: JSON.stringify({
      planId: p.planId, origin: point(p.from), destination: point(p.to), day: p.when?.day ?? null, minute: p.when?.minute ?? null, choice: p.choice,
      walker: p.walker || 'Walker', guardian: p.guardian || 'Guardian', guardianPhone: p.guardianPhone || null, backupName: p.backupName || null, backupPhone: p.backupPhone || null, thresholds: p.thresholds, replay: p.replay, timeScale: p.timeScale,
      notifyConsent: !!p.notifyConsent,
    }),
  });
  saveWalkCreds(w.walkId, { token: w.walkerToken, guardianUrl: w.guardianUrl, created: Date.now(), choice: p.choice, sharing: true });
  return w;
}

/** Wingman Wally: turn the guardian link on or off. Stopping revokes the link; starting issues a new one. */
export async function setSharing(walkId: string, active: boolean) {
  const creds = walkCreds(walkId);
  if (!creds) throw new Error('This phone does not hold the walker key for this walk.');
  const r = await call<{ active: boolean; guardianUrl: string | null }>(`/api/walks/${encodeURIComponent(walkId)}/share`, {
    method: 'POST', headers: { 'X-Walker-Token': creds.token }, body: JSON.stringify({ active }),
  });
  saveWalkCreds(walkId, { ...creds, guardianUrl: r.guardianUrl, sharing: r.active });
  return r;
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

// ---------------------------------------------------------------- Professor Hoot (the Head) and Sherlock Hoots (the Checker)
export interface TraceEvent {
  id: string; agent: AgentName; persona: string; tool: string; why: string; input: unknown; ok: boolean;
  status: 'ok' | 'error' | 'needs_approval' | 'skipped'; startedAt: number; ms: number; group?: number; summary: string;
}
/** @deprecated older trace shape; TraceEvent is a superset. */
export type TraceStep = TraceEvent;
export interface UnknownPlace { id: string; name: string; cat: string; lngLat: LngLat; atM: number; passMinute: number }
export interface HoursResult { id: string; name: string; status: 'hours found' | 'no hours' | 'closed' | 'not found' | 'check failed'; hours: string | null; source?: string | null; listingName?: string; checkedAt?: string }
export interface ApifyRun { actor: string; runId?: string | null; consoleUrl?: string | null; seconds: number; items: number; status?: string }
export interface CheckRun { ok: boolean; results: HoursResult[]; note: string; changed: number; mock?: boolean; run?: ApifyRun | null; evidence?: Evidence[]; reused?: number }
export interface Evidence {
  placeId: string; name: string;
  kind: 'published_hours' | 'no_published_hours' | 'listed_closed' | 'not_found' | 'check_failed';
  hours: string | null;
  source: { provider: 'apify' | 'mock' | 'osm' | 'apify-batch' | 'shopkeeper'; url?: string | null; actor?: string; runId?: string | null; consoleUrl?: string | null };
  retrievedAt: string | null; confidence: number | null; stale: boolean; reused: boolean; confirmedOpenNow: false; note: string;
}
export interface Approval {
  id: string; action: 'check_listed_hours'; provider: 'apify' | 'mock' | 'unavailable';
  places: { id: string; name: string; cat: string; passMinute: number; atM: number }[];
  maxUsd: number; reason: string; expiresAt: number;
}
export type Stats = DemoData['stats'];
export interface HeadAnswer {
  session: string; answer: string; by: string; trace: TraceEvent[]; ms: number; planId?: string; plan?: DemoData & { preferenceChoice?: PreferenceChoice | null };
  before?: Stats; after?: Stats; routeChanged?: boolean; inspection?: Inspection; unknowns?: UnknownPlace[]; check?: CheckRun;
  req?: { origin: { name: string; lat: number; lon: number }; destination: { name: string; lat: number; lon: number }; day: number; minute: number };
  preferences?: Preferences; preferenceChoice?: PreferenceChoice | null; pendingApproval?: Approval | null; evidence?: Evidence[];
  numbersCheck?: { ok: boolean; unverified: string[] };
}
export const askHead = (text: string, session?: string | null, allowChecks = false, signal?: AbortSignal) =>
  call<HeadAnswer>('/api/head/ask', { method: 'POST', signal, body: JSON.stringify({ text, session: session ?? null, allowChecks }) });
export const approveHead = (session: string, approvalId: string, approve: boolean) =>
  call<HeadAnswer>('/api/head/approve', { method: 'POST', body: JSON.stringify({ session, approvalId, approve }) });
export interface Inspection {
  verdict: string; good: boolean; score: number; minutes: number; arrive: string; route: RouteKey; note: string; missing: string[];
  items: { level: 'ok' | 'note' | 'warn'; title: string; detail: string; source: string }[];
}
/** Which engine candidate a call is about. */
export type RouteKey = 'best' | 'fast' | 'balanced';
export const inspectRoute = (planId: string, route: RouteKey = 'best') =>
  call<Inspection>('/api/check/route', { method: 'POST', body: JSON.stringify({ planId, route }) });
export const routeUnknowns = (planId: string) =>
  call<{ places: UnknownPlace[]; total: number | null; apify: boolean }>('/api/check/unknowns', { method: 'POST', body: JSON.stringify({ planId }) });
export type HoursCheck = CheckRun & { before: Stats; after: Stats; routeChanged: boolean; planId: string; plan: Plan; evidence: Evidence[]; reused: number; run: ApifyRun | null };
/** The button press is the approval: confirm must be true or the server answers 428. */
export const checkHours = (planId: string, placeIds: string[] | undefined, confirm: true, route?: RouteKey) =>
  call<HoursCheck>('/api/check/hours', { method: 'POST', body: JSON.stringify({ planId, placeIds, route, confirm }) });

export interface EvidencePlace {
  id: string; name: string; cat: string; lngLat: LngLat; atM: number; passMinute: number; hours: string | null; openAtPass: boolean | null;
  evidence: { kind: 'osm_tag' | 'listing_batch' | 'listing_live' | 'shopkeeper' | 'none'; provider: string; url?: string | null; retrievedAt?: string | null; stale: boolean; note: string };
}
export interface PlanEvidence { route: RouteKey; places: EvidencePlace[]; counts: { listed: number; live: number; shopkeeper: number; unknown: number; stale: number } }
export const planEvidence = (planId: string, route: RouteKey = 'best') =>
  call<PlanEvidence>(`/api/plans/${encodeURIComponent(planId)}/evidence?route=${route}`);

export interface AgentInfo { id: AgentName; persona: string; job: string; runsOn: string; live: boolean }
export const agents = () => call<AgentInfo[]>('/api/agents');
export const health = () => call<Health>('/api/health');

export type { RouteStats };
