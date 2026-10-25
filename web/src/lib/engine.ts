import { along, cumulative, lineLength, project, turnsFromSteps, type Turn } from './geo';
import { AGENT_LABEL, clock, isListedOpen, openSpoken } from './format';
import type { Room } from './transport';
import type { AgentName, DemoData, Envelope, LngLat, Msg, Place } from './types';
import type { Settings } from './store';
import { PERSONA } from './personas';

// Deterministic demo engine: plays the four agents from cached data when the
// gateway isn't driving the walk (?agents=demo). It is scripted: every screen it drives is labelled "Simulated demo".
// It speaks the same message types the real agents send, so every screen behaves
// identically in both modes. It replays the route as GPS (badged "Demo · GPS replay")
// and injects one stop on the engine-selected stretch.

const WALK_MS = 1.35; // walking speed, m/s
const TICK = 500;

export class DemoEngine {
  private room: Room;
  private data: DemoData;
  private settings: Settings;
  private unsub: () => void;
  private timer?: number;
  private timeouts: number[] = [];
  private line: LngLat[] = [];
  private cum: number[] = [];
  private total = 0;
  private progress = 0;
  private turnsList: Turn[] = [];
  private said = new Set<string>();
  private stopAt = Infinity;
  private state: 'idle' | 'walking' | 'stopped' | 'asking' | 'escalated' | 'done' = 'idle';
  private places: Place[];
  private stats: DemoData['stats'];
  private mine = new Set<string>();
  // If another engine (another tab/device) plans or starts the walk, this one stands down.
  private passive = false;
  running = false;

  constructor(room: Room, data: DemoData, settings: Settings) {
    this.room = room;
    this.data = data;
    this.settings = settings;
    this.places = data.places.map((p) => ({ ...p }));
    this.stats = structuredClone(data.stats);
    this.unsub = room.subscribe((e) => this.onMessage(e));
  }

  private sending = false;
  private send(m: Msg) {
    // Room.send delivers to local listeners synchronously, so flag our own echo.
    this.sending = true;
    try {
      const env = this.room.send(m, 'engine');
      this.mine.add(env.id);
      if (this.mine.size > 2000) this.mine.clear();
    } finally {
      this.sending = false;
    }
  }
  private log(agent: AgentName, text: string, reason: string, to?: string, at?: number) {
    this.send({ type: 'agent.log', agent, text, reason, to, at });
  }
  private say(agent: AgentName, text: string) {
    this.send({ type: 'voice.say', agent, text });
  }
  private later(ms: number, f: () => void) {
    this.timeouts.push(window.setTimeout(f, ms));
  }
  private scaled(sec: number) {
    return (sec * 1000) / Math.max(1, this.settings.timeScale);
  }

  /** The Guide's offer before leaving. Called when the walker opens /walk. */
  plan() {
    this.stopTimers();
    this.state = 'idle';
    this.running = false;
    this.passive = false;
    this.stats = structuredClone(this.data.stats);
    const d = this.data;
    const overnight = new Date();
    overnight.setHours(2, 0, 4, 0);
    this.log('head', `Cached conditions cover ${d.scenario.segmentsScored.toLocaleString()} street segments.`, 'Simulated demo from cached OSM streets, listed place hours, and SF 311 streetlight records.', PERSONA.guide, overnight.getTime());
    this.log('guide', `Which places are listed open along ${d.start.name} → ${d.end.name}?`, 'Checking the cached hours at each arrival minute.', PERSONA.checker);
    const open = this.places.filter((p) => isListedOpen(p.openUntil));
    this.later(500, () => {
      for (const p of open) this.log('guide', `Listed hours · ${p.name}: ${p.openUntil === '24h' ? 'open 24h' : p.openUntil === 'lobby' ? 'lobby open' : `open until ${clock(p.openUntil)}`}.`, 'Cached place hours; shopkeeper interaction is simulated.');
      this.sendPlan(`The route scores ${d.stats.hootroute.score} versus ${d.stats.shortest.score}. Its longest stretch without a listed open place or help point is ${d.stats.hootroute.longestEmptyM} m versus ${d.stats.shortest.longestEmptyM} m. Conditions, not a safety rating.`);
    });
  }

  private sendPlan(reason: string) {
    this.send({ type: 'walk.plan', plan: { routeId: 'route-1', stats: structuredClone(this.stats), reason: `Simulated demo. ${reason}`, thresholds: this.settings.thresholds, guardian: this.settings.guardianName } });
  }

  start(choice: 'hootroute' | 'usual') {
    this.stopTimers();
    this.passive = false;
    this.running = true;
    this.line = choice === 'hootroute' ? this.data.route : this.data.shortest;
    this.cum = cumulative(this.line);
    this.total = lineLength(this.line);
    this.turnsList = turnsFromSteps(this.data.routeSteps[choice === 'usual' ? 'shortest' : 'hootroute'], this.total);
    this.progress = 0;
    this.said.clear();
    const stop = project(this.line, this.data.stopAt, this.cum);
    this.stopAt = stop.offset < 40 ? stop.meters : this.total * 0.72;
    this.state = 'walking';
    this.send({ type: 'walk.accept', choice });
    this.send({ type: 'walk.start', replay: true });
    this.log('guide', `WalkPlan sent: ${choice === 'hootroute' ? 'HootRoute route' : 'shortest route'}. Score ${this.stats.hootroute.score} vs ${this.stats.shortest.score}.`, `${this.settings.walkerName} chose this route.`, PERSONA.checker);
    const first = this.turnsList[0];
    const firstStreet = this.data.routeSteps[choice === 'usual' ? 'shortest' : 'hootroute'].find((s) => s.street !== 'the path')?.street ?? 'the walking path';
    this.say('guide', `Okay, I'm walking with you. Head toward ${firstStreet}${first && first.direction !== 'arrive' ? `, then ${first.direction} on ${first.street}` : ''}.`);
    this.timer = window.setInterval(() => this.tick(), TICK);
    this.tick();
  }

  private tick() {
    if (this.state === 'walking') {
      this.progress = Math.min(this.total, this.progress + WALK_MS * this.settings.timeScale * (TICK / 1000));
      if (this.progress >= this.stopAt && this.stopAt !== Infinity) {
        this.progress = this.stopAt;
        this.stopAt = Infinity;
        this.state = 'stopped';
        this.onStopped();
      }
    }
    const p = along(this.line, this.progress, this.cum);
    this.send({ type: 'walk.position', lngLat: p.lngLat, heading: p.heading, speed: this.state === 'walking' ? WALK_MS : 0, progress: this.progress / this.total, replay: true });
    if (this.state === 'walking') this.narrate();
    if (this.progress >= this.total - 0.5 && this.state === 'walking') this.arrive();
  }

  private narrate() {
    const m = this.progress;
    // turns: announce ~120 m out (or as soon as the leg starts if shorter)
    for (const t of this.turnsList) {
      const key = `turn:${t.meters}`;
      if (t.direction === 'arrive' || this.said.has(key)) continue;
      if (t.meters - m <= 130 && t.meters > m) {
        this.said.add(key);
        const left = Math.max(10, Math.round((t.meters - m) / 10) * 10);
        this.say('guide', `${cap(t.direction)} on ${title(t.street)} in about ${left} metres.`);
        return;
      }
    }
    // open places just ahead
    for (const p of this.places) {
      const key = `place:${p.id}`;
      if (this.said.has(key) || !isListedOpen(p.openUntil)) continue;
      const pr = project(this.line, p.lngLat, this.cum);
      if (pr.offset < 45 && pr.meters - m < 70 && pr.meters - m > 0) {
        this.said.add(key);
        this.say('checker', `${p.name} is just ahead, ${openSpoken(p)}.`);
        if (!p.simulated) this.log('checker', `Passing ${p.name} (${openSpoken(p)}).`, 'Cached listed hours: published hours, not confirmation the place is staffed.');
        return;
      }
    }
    // dim stretch heads-up
    for (const d of this.data.dimStretches) {
      const key = `dim:${d.id}`;
      if (this.said.has(key)) continue;
      const pr = project(this.line, d.line[0], this.cum);
      if (pr.offset < 25 && pr.meters - m < 60 && pr.meters - m > -10) {
        this.said.add(key);
        this.say('checker', `The next ${d.meters} metres have fewer mapped streetlights. I'm with you.`);
        return;
      }
    }
  }

  private onStopped() {
    const t = this.settings.thresholds;
    const dim = this.data.dimStretches.find((d) => d.onRoute);
    this.log('checker', `Stopped on ${dim?.name ?? 'a stretch with fewer open places'} (score ${dim?.score ?? '—'}). Waiting ${t.stopSeconds} s before asking.`, 'A stretch without a listed open place or help point.');
    this.later(this.scaled(t.stopSeconds), () => {
      if (this.state !== 'stopped') return;
      this.state = 'asking';
      const deadline = Date.now() + this.scaled(t.replySeconds);
      this.send({ type: 'checkin.ask', agent: 'checker', text: 'You stopped. All good?', reason: `You've been still for ${t.stopSeconds} s on ${dim?.name ?? 'the route'}.`, windowSec: t.replySeconds, deadline });
      this.say('checker', 'You stopped. All good?');
      this.log('checker', 'Asked aloud: "You stopped. All good?"', `Still for ${t.stopSeconds} s on a low-score segment.`, this.settings.walkerName);
      this.later(this.scaled(t.replySeconds) + 50, () => {
        if (this.state === 'asking') this.escalate(`No reply for ${t.replySeconds} s`);
      });
    });
  }

  private escalate(reason: string) {
    this.state = 'escalated';
    const p = along(this.line, this.progress, this.cum);
    const where = this.data.dimStretches.find((d) => d.onRoute)?.name ?? this.data.end.name;
    this.log('checker', 'Escalating with last position and trace.', `${reason}. Standing order: guardian first.`, PERSONA.rescuer);
    this.send({ type: 'escalate', reason, lngLat: p.lngLat });
    this.send({ type: 'guardian.alert', reason, lngLat: p.lngLat, where });
    this.log('rescuer', `Alert sent to ${this.settings.guardianName.split(' ')[0]}'s live link. Handoff packet written. 911 not contacted.`, 'Simulated demo. HootRoute never calls emergency services.', 'Guardian');
    this.say('rescuer', `I've sent ${this.settings.guardianName.split(' ')[0]} your live location. Say "I'm fine" or tap the button if you're okay.`);
    this.later(this.scaled(this.settings.thresholds.escalateSeconds), () => {
      if (this.state === 'escalated') this.log('rescuer', 'Guardian has not cleared the alert. Handoff packet ready: position, route, time, reason.', 'Simulated demo: nobody else is contacted and 911 is never called. A person can tap Call 911.');
    });
  }

  private resume(why: string) {
    this.state = 'walking';
    this.say('checker', 'Okay. Walking with you.');
    this.log('checker', `Check-in cleared (${why}). Resuming the walk.`, 'Walker answered.');
  }

  private arrive() {
    this.state = 'done';
    this.running = false;
    window.clearInterval(this.timer);
    this.say('head', `You've arrived at ${this.data.end.name}, ${this.settings.walkerName}.`);
    this.send({ type: 'walk.end', outcome: 'arrived', summary: `Arrived near ${this.data.end.name}. Route conditions recorded; nothing was submitted to the city.` });
    this.log('head', 'Walk ended. Route conditions recorded; any 311 report remains a draft.', 'No report was submitted.');
  }

  private onMessage(e: Envelope) {
    const m = e.msg;
    if (this.sending || this.mine.has(e.id)) return;
    if (m.type === 'walk.reset') {
      this.stopTimers();
      this.state = 'idle';
      this.running = false;
      this.passive = false;
      return;
    }
    if (e.from === 'engine' && (m.type === 'walk.plan' || m.type === 'walk.start')) {
      this.passive = true;
      this.stopTimers();
      this.state = 'idle';
      this.running = false;
      return;
    }
    if (e.from === 'engine' || this.passive) return;
    if (m.type === 'checkin.reply') {
      if (m.reply === 'fine' && (this.state === 'asking' || this.state === 'escalated' || this.state === 'stopped')) {
        if (this.state === 'escalated') this.log('rescuer', 'Walker said they are fine. Guardian alert cleared.', 'Check-in answered after escalation.', 'Guardian');
        this.resume(m.via === 'voice' ? 'said "I\'m fine"' : 'tapped I\'m fine');
      } else if (m.reply === 'help' && this.state !== 'escalated' && this.state !== 'done') {
        if (this.state === 'walking') this.state = 'stopped';
        this.escalate('Walker asked for help');
      }
    }
    if (m.type === 'guardian.ack' && this.state === 'escalated') {
      this.say('rescuer', `${m.by} is on it.`);
      this.log('rescuer', `${m.by} cleared the alert: "I'm on it".`, 'Guardian responded.', this.settings.walkerName);
    }
    if (m.type === 'place.update') this.onPlaceUpdate(m.place);
    if (m.type === 'audit.run') this.runAudit();
  }

  private onPlaceUpdate(u: Pick<Place, 'id' | 'openUntil' | 'safeHaven' | 'frontLight'>) {
    const p = this.places.find((x) => x.id === u.id);
    if (!p) return;
    Object.assign(p, u);
    const open = isListedOpen(u.openUntil);
    this.log('guide', `Place update · ${p.name}: ${open ? `staying open until ${clock(u.openUntil)}` : 'closed for the night'}${u.frontLight ? ', front light on' : ''}.`, p.simulated ? 'Simulated shopkeeper declaration.' : 'Shopkeeper declaration.');
    const scenario = this.data.whatIf;
    if (scenario && p.id === scenario.placeId) {
      const [hour, minute] = u.openUntil.split(':').map(Number);
      const until = u.openUntil === '24h' ? Infinity : Number.isFinite(hour) && Number.isFinite(minute) ? hour * 60 + minute + (hour < 12 ? 1440 : 0) : -1;
      const countsOpen = open && until > scenario.passMinute;
      this.stats = structuredClone(countsOpen ? scenario.statsOpen : this.data.stats);
      this.log('guide', `Engine replay re-scored the fixed routes: ${this.stats.hootroute.score} vs ${this.stats.shortest.score}.`, `Cached Python engine result for ${p.name} ${countsOpen ? 'open' : 'closed'} at the arrival minute.`);
      if (this.state === 'idle' || this.state === 'walking') this.sendPlan(`${p.name} is ${countsOpen ? 'listed open' : 'not listed open'} when the walker passes. The fixed routes score ${this.stats.hootroute.score} versus ${this.stats.shortest.score}.`);
      if (this.state === 'walking') {
        const pr = project(this.line, p.lngLat, this.cum);
        if (pr.meters > this.progress) this.say('guide', `${p.name} has updated its hours. I have refreshed the route conditions.`);
      }
    }
  }

  private runAudit() {
    this.log('head', 'Running the cached overnight audit.', 'Requested from the control room.');
    this.later(1400, () => {
      const ranking = this.data.darknessDebt;
      const top = ranking[0];
      this.send({ type: 'audit.result', ranking, draft311: `DRAFT — not submitted. Review streetlight conditions on ${top.street}. The model estimates ${top.minutes} walker-minutes on lower-light segments in a simulated overnight sample. Confirm conditions and report identifiers before filing.` });
      this.log('head', `Ranked modeled walker-minutes on lower-light streets. Top: ${top.street} (${top.minutes} min). Draft 311 text prepared.`, 'Modeled trips, not observed foot traffic. Report remains a draft.');
    });
  }

  private stopTimers() {
    window.clearInterval(this.timer);
    this.timeouts.forEach((t) => window.clearTimeout(t));
    this.timeouts = [];
  }

  dispose() {
    this.stopTimers();
    this.unsub();
    this.running = false;
  }
}

function title(s: string) {
  return s
    .toLowerCase()
    .replace(/\b(\w)/g, (c) => c.toUpperCase())
    .replace(/\bSt\b/, 'St');
}
function cap(s: string) {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

export { AGENT_LABEL };
