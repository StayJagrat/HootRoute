export type LL = [number, number] // lon, lat
export interface Shop { id: string; d: number; off: number; name: string | null; cat: string; ll: LL; hours: string | null }
export interface Step { street: string; maneuver: string; at_m: number; len_m: number; ll: LL }
export interface Route {
  id: 'fast' | 'best'; label: string; score: number; points: Record<string, number>; weights: Record<string, number>
  minutes: number; km: number; places_open: number; gap: { m: number; range: [number, number] | null }
  light_pct: number; main_pct: number; turns_per_km: number; outages_near: number; light_known_pct: number; unknown_hours_nearby: number
  coords: LL[]; shops: Shop[]; covered: boolean[]; steps: Step[]
}
export interface RouteResponse { depart: { day: string; minute: number }; recommended: string; routes: Route[]; candidates: number; ms: number }
export interface AgentEvent { ts: number; agent: string; kind: string; msg: string; data: Record<string, any> }
export interface Landmark { name: string; lat: number; lon: number }
export interface Meta { bbox: [number, number, number, number]; weights: Record<string, number>; stats: Record<string, number>; bart: { name: string; ll: LL }[] }
export type PlaceRow = [string, number, number, string, string, number, number] // id, lon, lat, name, cat, open(-1 unknown, 0, 1), declared
export interface WalkState {
  id: string; walker: string; guardian: string; status: 'walking' | 'checkin' | 'alert' | 'escalated' | 'cleared' | 'arrived'; d: number; ll: LL
  last_checkin: string; minutes: number; km: number; coords: LL[]; shops: Shop[]; gap: Route['gap']; score: number; steps: Step[]
  req: { origin: { lat: number; lon: number }; dest: { lat: number; lon: number }; day: number; minute: number }
}
export interface WhyStreet { street: string; score: number; light_pct: number; open: { name: string; hours: string | null; src?: string }[]; lamps: number; outages: number; unknown_hours: number; ll: LL; text: string }
export interface DebtRow { street: string; minutes: number; segments: number; ll: LL }
