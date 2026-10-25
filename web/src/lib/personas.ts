import type { AgentName } from './types';

/** Display names for the four agents. Internal ids (head, guide, checker, rescuer) never change.
 *  To go back to the plain role names, set USE_PERSONAS to false. */
const USE_PERSONAS = true;

export const ROLE: Record<AgentName, string> = { head: 'Head', guide: 'Guide', checker: 'Checker', rescuer: 'Rescuer' };

const NAMES: Record<AgentName, string> = { head: 'Professor Hoot', guide: 'Scoot McRoute', checker: 'Sherlock Hoots', rescuer: 'Wingman Wally' };

export const PERSONA: Record<AgentName, string> = USE_PERSONAS ? NAMES : ROLE;

/** Short first name for running copy ("Scoot is planning routes…"). */
export const SHORT: Record<AgentName, string> = USE_PERSONAS ? { head: 'Hoot', guide: 'Scoot', checker: 'Sherlock', rescuer: 'Wally' } : ROLE;

/** What each agent does and what it runs on (mirrors GET /api/agents; used when the gateway is offline). */
export const JOB: Record<AgentName, { job: string; runsOn: string }> = {
  head: { job: 'Reads your request, picks the tools, asks before any paid check, and explains every choice.', runsOn: 'Claude tool use (a fixed pipeline without a key)' },
  guide: { job: 'Plans candidate routes and scores each block at the minute you pass it, then re-plans around obstacles.', runsOn: 'Deterministic Python engine' },
  checker: { job: 'Finds unknown or stale hours on the route and checks published listings after you approve.', runsOn: 'Apify Google Maps listings + a deterministic parser' },
  rescuer: { job: 'Handles your live journey: obstacle reports, route recovery, sharing on and off, and check-ins.', runsOn: 'Walk rooms and rules; texts or calls only with your opt-in' },
};
