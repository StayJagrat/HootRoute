// Message contract between the PWA screens, the gateway and the agents.
// Every message travels in an Envelope inside one room per walk.
// The gateway (FastAPI) and the dev relay both just forward envelopes;
// the Brain's agents produce the same types the local demo engine produces.

export type LngLat = [number, number];
export type AgentName = 'head' | 'guide' | 'checker' | 'rescuer';
export type MascotState = 'idle' | 'talking' | 'thinking' | 'done';

export interface Place {
  id: string;
  name: string;
  kind: 'cafe' | 'market' | 'pharmacy' | 'hotel';
  lngLat: LngLat;
  openUntil: string; // "01:00", "24h", "lobby", or "closed"
  safeHaven: boolean;
  frontLight?: boolean;
  simulated: boolean;
  address?: string | null;
  hoursSource?: string | null; // osm | apify | shopkeeper ...
}

export interface DimStretch {
  id: string;
  name: string;
  onRoute: boolean;
  meters: number;
  score: number;
  confidence: 'low' | 'medium' | 'high';
  line: LngLat[];
  lampEvidence: string;
  lampSource: string;
  openPlaces: string;
  openSource: string;
  why: string;
}

export interface RouteStats {
  score: number;
  longestEmptyM: number;
  minutes: number;
}

export interface RouteStep {
  street: string;
  maneuver: string;
  at_m: number;
  len_m: number;
  ll: LngLat;
}

export interface RouteOption {
  id: 'fast' | 'balanced' | 'best';
  label: string;
  coords: LngLat[];
  steps: RouteStep[];
  stats: RouteStats;
  km: number;
  placesOpen: number;
  lightPct: number;
  points: Record<string, number>;
  weights: Record<string, number>;
}

export interface DemoData {
  scenario: { label: string; area: string; segmentsScored: number; departureMinute: number; day?: number };
  walker: { id: string; name: string };
  guardian: { name: string; initials: string; channel: string };
  start: { name: string; lngLat: LngLat };
  end: { name: string; lngLat: LngLat };
  route: LngLat[];
  shortest: LngLat[];
  dimStretches: DimStretch[];
  stopAt: LngLat;
  places: Place[];
  stats: { streetwise: RouteStats; shortest: RouteStats };
  darknessDebt: { street: string; minutes: number }[];
  routeSteps: { streetwise: RouteStep[]; shortest: RouteStep[] };
  options?: RouteOption[];
  recommended?: 'fast' | 'balanced' | 'best';
  whatIf?: { placeId: string; passMinute: number; statsOpen: DemoData['stats'] } | null;
  dataNote?: string;
}

export interface Thresholds {
  stopSeconds: number; // stop on a dim stretch before the Checker asks (default 90)
  replySeconds: number; // check-in reply window (default 45)
  escalateSeconds: number; // guardian has this long to clear before the ladder continues (default 90)
}

// ---------------------------------------------------------------- messages
export type Msg =
  | { type: 'walk.plan'; plan: WalkPlan }
  | { type: 'walk.reset' }
  | { type: 'walk.accept'; choice: 'streetwise' | 'usual'; guardian?: string; thresholds?: Thresholds; origin?: { lat: number; lon: number }; dest?: { lat: number; lon: number }; day?: number; minute?: number }
  | { type: 'walk.start'; replay: boolean }
  | { type: 'walk.position'; lngLat: LngLat; heading: number; speed: number; progress: number; replay: boolean; accuracy?: number }
  | { type: 'voice.say'; agent: AgentName; text: string }
  | { type: 'checkin.ask'; agent: 'checker'; text: string; reason: string; windowSec: number; deadline: number }
  | { type: 'checkin.reply'; reply: 'fine' | 'help'; via: 'voice' | 'tap' }
  | { type: 'escalate'; reason: string; lngLat: LngLat }
  | { type: 'guardian.alert'; reason: string; lngLat: LngLat; where: string }
  | { type: 'guardian.ack'; by: string }
  | { type: 'guardian.join'; name: string }
  | { type: 'place.update'; place: Pick<Place, 'id' | 'openUntil' | 'safeHaven' | 'frontLight'> }
  | { type: 'agent.log'; agent: AgentName; to?: string; text: string; reason: string; at?: number }
  | { type: 'walk.end'; outcome: 'arrived' | 'ended' | 'incident'; summary: string; draft311?: string; reportBy?: string }
  | { type: 'rescue.ladder'; step: number; label: string; status: string; steps: string[] }
  | { type: 'audit.run' }
  | { type: 'audit.result'; ranking: { street: string; minutes: number }[]; draft311: string; cases?: { id: string; opened: string; details: string }[] };

/** The Guide's plan. In live mode `data` carries the whole route, so every screen on every device draws the same walk. */
export interface WalkPlan {
  routeId: string;
  stats: DemoData['stats'];
  reason: string;
  thresholds: Thresholds;
  guardian: string;
  walker?: string;
  replay?: boolean;
  timeScale?: number;
  data?: DemoData;
}

export interface Envelope<M extends Msg = Msg> {
  id: string;
  walkId: string;
  ts: number; // ms epoch
  from: 'walker' | 'guardian' | 'shop' | 'room' | 'engine' | 'gateway';
  msg: M;
}
