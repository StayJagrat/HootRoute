import { along, cumulative, lineLength, project } from './geo';
import type { LngLat, Msg } from './types';

// GPS replay for indoor demos (?gps=replay). It only produces positions; the live agents on the gateway decide
// everything else, exactly as they would for a real walk. Every screen shows the "DEMO · GPS REPLAY" tape.
// It walks the route at timeScale× walking speed and stands still at `stopAt` until resume() (the walker answered)
// or until maxHoldMs, so the Checker's stop rule fires on the engine-chosen stretch.

const WALK_MS = 1.35;
const TICK = 500;

export class GpsReplay {
  private timer?: number;
  private meters = 0;
  private holdUntil = 0;
  private held = false;
  private cum: number[];
  private total: number;
  private stopM: number;

  constructor(
    private send: (m: Msg) => void,
    private line: LngLat[],
    stopAt: LngLat | null,
    private timeScale: number,
    private maxHoldMs: number,
    leadInM?: number,   // stage demos: start this far before the stop instead of at the origin (the tape still says REPLAY)
  ) {
    this.cum = cumulative(line);
    this.total = lineLength(line);
    const s = stopAt ? project(line, stopAt, this.cum) : null;
    this.stopM = s && s.offset < 40 ? s.meters : Infinity;
    if (leadInM !== undefined && Number.isFinite(this.stopM)) this.meters = Math.max(0, this.stopM - leadInM);
  }

  start() {
    this.stop();
    this.timer = window.setInterval(() => this.tick(), TICK);
    this.tick();
  }

  /** The walker said they're fine: walk on. */
  resume() {
    this.holdUntil = 0;
  }

  stop() {
    window.clearInterval(this.timer);
    this.timer = undefined;
  }

  get running() {
    return this.timer !== undefined;
  }

  private tick() {
    const now = Date.now();
    if (!this.held && this.meters >= this.stopM) {
      this.held = true;
      this.holdUntil = now + this.maxHoldMs;
    }
    const holding = this.held && now < this.holdUntil;
    if (!holding) this.meters = Math.min(this.total, this.meters + WALK_MS * this.timeScale * (TICK / 1000));
    const p = along(this.line, this.meters, this.cum);
    this.send({ type: 'walk.position', lngLat: p.lngLat, heading: p.heading, speed: holding ? 0 : WALK_MS, progress: this.meters / this.total, replay: true });
    if (this.meters >= this.total) this.stop();
  }
}
