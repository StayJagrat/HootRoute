# HootRoute agent API (branch `agentic`)

The contract between the PWA (`web/`) and the gateway (`services/api`) for the agent features: approval-gated
investigation, evidence with provenance, Mission Recovery, and guardian sharing that can be stopped. Older endpoints in
`docs/BACKEND.md` keep working. Every number in a response comes from the deterministic engine.

## Personas

Internal agent ids stay `head | guide | checker | rescuer` (message `agent` fields, mascots, uAgents seeds). The UI shows
persona names from `GET /api/agents`:

| id | Persona | Job | Runs on |
|---|---|---|---|
| `head` | Professor Hoot | Reads the request, extracts preferences, picks tools, asks before paid checks, explains, coordinates recovery | Claude tool use (fixed pipeline without a key) |
| `guide` | Scoot McRoute | Candidate routes, scores at the minute you pass each block, preference ranking, re-plans around obstacles | Deterministic Python engine |
| `checker` | Sherlock Hoots | Finds unknown or stale hours on the route, checks published listings after approval, records source and time | Apify Google Maps actor + deterministic parser |
| `rescuer` | Wingman Wally | Live journey: obstacle reports, recovery choices, sharing on/off, check-in escalation ladder | Walk rooms + rules, Twilio only with opt-in |

```
GET /api/agents -> [{ id, persona, job, runsOn, live: bool }]
```

## Trace events

`POST /api/head/ask` and `POST /api/head/approve` return `trace: TraceEvent[]`, one per real tool execution:

```ts
interface TraceEvent {
  id: string;              // unique per event
  agent: 'head' | 'guide' | 'checker' | 'rescuer';
  persona: string;         // "Scoot McRoute"
  tool: string;            // find_place | plan_routes | inspect_route | find_route_unknowns | propose_hours_check
                           // | check_listed_hours | rescore_routes | replan_avoiding | rank_by_preferences
  why: string;             // the reason Claude gave for the call (or the fixed pipeline's rule)
  input: unknown;
  ok: boolean;
  status: 'ok' | 'error' | 'needs_approval' | 'skipped';
  startedAt: number;       // ms epoch
  ms: number;
  group?: number;          // calls in the same group ran concurrently
  summary: string;         // one line, numbers from the tool result
}
```

## Professor Hoot

```
POST /api/head/ask { text, session?, allowChecks?: false }
```
`allowChecks` now defaults to **false**. When Hoot decides a paid check is worth it, it does not run it; the response
carries `pendingApproval` and the answer says what it would check and why.

```ts
interface HeadAnswer {
  session: string; answer: string; by: string;          // "Claude (claude-sonnet-5-5)" | "fixed pipeline (...)"
  trace: TraceEvent[]; ms: number;
  planId?: string; plan?: Plan; req?: { origin, destination, day, minute };
  before?: Stats; after?: Stats; routeChanged?: boolean;
  inspection?: Inspection; unknowns?: UnknownPlace[];
  preferences?: Preferences;                             // what Hoot extracted, typed
  preferenceChoice?: { optionId: 'fast'|'balanced'|'best'; reason: string } | null;
  pendingApproval?: Approval | null;
  check?: CheckRun; evidence?: Evidence[];
  numbersCheck: { ok: boolean; unverified: string[] };   // numbers in `answer` not found in any tool result
}
interface Preferences { fewerTurns: boolean; preferOpenPlaces: boolean; preferMainRoads: boolean; fastest: boolean; lowDistraction: boolean; notes?: string }
interface Approval {
  id: string; action: 'check_listed_hours'; provider: 'apify' | 'mock' | 'unavailable';
  places: { id: string; name: string; cat: string; passMinute: number; atM: number }[];
  maxUsd: number; reason: string; expiresAt: number;     // ms epoch
}
```
If `numbersCheck.ok` is false, the gateway replaced Claude's prose with a deterministic summary (`by` says so).

```
POST /api/head/approve { session, approvalId, approve: boolean }
```
`approve: true` runs exactly the approved check (no other places), applies evidence, re-scores, and Hoot explains what
changed or why nothing changed. Returns a `HeadAnswer`. `approve: false` returns an answer that says nothing was checked.
Errors: 404 unknown or expired approval, 429 rate or daily budget exceeded.

## Sherlock Hoots: evidence

```ts
interface Evidence {
  placeId: string; name: string;
  kind: 'published_hours' | 'no_published_hours' | 'listed_closed' | 'not_found' | 'check_failed';
  hours: string | null;            // OSM opening_hours syntax
  source: { provider: 'apify' | 'mock' | 'osm' | 'apify-batch' | 'shopkeeper'; url?: string | null; actor?: string; runId?: string | null; consoleUrl?: string | null };
  retrievedAt: string | null;      // ISO 8601
  confidence: number | null;       // parser confidence 0..1
  stale: boolean;                  // older than EVIDENCE_STALE_DAYS (default 30)
  reused: boolean;                 // served from earlier evidence, no new provider call
  confirmedOpenNow: false;         // HootRoute never confirms a place is staffed
  note: string;
}
```

```
POST /api/check/hours { planId, placeIds?, route?: 'best'|'fast', confirm: true }
```
`confirm` is required (428 without it): the button press is the approval. Adds `evidence: Evidence[]`, `reused: number`,
and `run: { actor, runId, consoleUrl, seconds, items, status } | null`. Places checked within `EVIDENCE_TTL_HOURS`
(default 12) are reused and not re-billed.

```
GET /api/plans/{planId}/evidence?route=best|fast
-> { route, places: EvidencePlace[], counts: { listed: number; live: number; shopkeeper: number; unknown: number; stale: number } }

interface EvidencePlace {
  id: string; name: string; cat: string; lngLat: LngLat; atM: number; passMinute: number;
  hours: string | null;
  openAtPass: boolean | null;      // null = unknown hours (never shown as closed or risky)
  evidence: { kind: 'osm_tag' | 'listing_batch' | 'listing_live' | 'shopkeeper' | 'none'; provider: string; url?: string | null;
              retrievedAt?: string | null; stale: boolean; note: string };
}
```

## Scoot McRoute: preferences and alternatives

`POST /api/plans` accepts `preferences?: Partial<Preferences>` and returns `preferenceChoice`. Walks accept
`choice: 'hootroute' | 'usual' | 'balanced'` (`balanced` only when the plan has that option).

## Wingman Wally: live journey

### Sharing
`POST /api/walks` now returns a guardian link with its own token: `guardianUrl = <base>/guardian/<walkId>?g=<guardianToken>`.
The guardian WebSocket must pass it: `/ws?walk=<id>&role=guardian&token=<guardianToken>`. Without a valid token the
socket closes with 4401. Body gains `notifyConsent: boolean` (default false): without it no SMS or call is ever sent.

```
POST /api/walks/{walkId}/share { active: boolean }      header X-Walker-Token
-> { active: boolean, guardianUrl: string | null }
```
Stopping revokes the guardian token, disconnects guardian sockets and publishes `{type:'share.update', active:false}`.
Starting again issues a new token (old links stay dead). While sharing is off the Rescuer sends no SMS or call.

### Mission Recovery (WebSocket messages)
```ts
// walker -> room
{ type: 'obstacle.report'; kind: 'blocked' | 'construction' | 'place_closed' | 'want_detour' | 'other'; note?: string; lngLat?: LngLat }
{ type: 'recovery.choose'; recoveryId: string; optionId: string }     // optionId 'keep' keeps the current route

// agents -> room
{ type: 'recovery.options'; recoveryId: string; kind: string; reason: string; at: LngLat;
  current: RecoveryOption; options: RecoveryOption[]; explanation: string; explainedBy: string; expiresAt: number }
interface RecoveryOption { id: string; label: string; coords: LngLat[]; stats: RouteStats; km: number; turnsPerKm: number;
                           avoidsReport: boolean; liveEvidence: number }
{ type: 'share.update'; active: boolean }
```
The active route never changes until the walker sends `recovery.choose`. A chosen option arrives as a normal
`walk.plan` whose `reason` starts with "Switched after your report".

## Limits

Per-IP token buckets (HTTP 429 with `Retry-After`): `/api/head/*` 12/min, `/api/check/hours` 4/min,
`/api/block-vision` 10/min, `/api/voice/tts` 30/min, `/api/plans` 30/min, `/api/walks` 10/min. A daily cap on paid hours
checks (`APIFY_DAILY_RUNS`, default 25). Each check is capped at `maxTotalChargeUsd=0.5`.
