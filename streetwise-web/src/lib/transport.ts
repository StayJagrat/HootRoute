import { adminToken, walkCreds } from './api';
import type { Envelope, Msg } from './types';

// One Room per walk. It talks to the gateway over WebSocket when it can,
// and to other tabs on the same device over BroadcastChannel always.
// Envelopes are de-duplicated by id, so both paths can run at once.
//
// Gateway URL resolution:
//   1. VITE_GATEWAY_URL (e.g. wss://gateway.example.com/ws)
//   2. same origin /ws  (the dev relay, proxied by Vite — works through one HTTPS tunnel)
// Wire format: the gateway/relay forwards Envelope JSON to everyone in the walk's room,
// and may send {kind:"history", envelopes:[...]} to a client that just joined.

export type Role = Envelope['from'];
export type LinkStatus = 'connecting' | 'online' | 'local';
type Listener = (e: Envelope) => void;

const uid = () => Math.random().toString(36).slice(2, 10) + Date.now().toString(36);

export class Room {
  readonly walkId: string;
  readonly role: Role;
  status: LinkStatus = 'connecting';
  private ws?: WebSocket;
  private bc?: BroadcastChannel;
  private seen = new Set<string>();
  private listeners = new Set<Listener>();
  private statusListeners = new Set<(s: LinkStatus) => void>();
  private retry = 0;
  private closed = false;
  private outbox: string[] = [];

  constructor(walkId: string, role: Role) {
    this.walkId = walkId;
    this.role = role;
    if ('BroadcastChannel' in window) {
      this.bc = new BroadcastChannel(`streetwise:${walkId}`);
      this.bc.onmessage = (ev) => this.receive(ev.data as Envelope);
    }
    this.connect();
  }

  private url(): string {
    const env = import.meta.env.VITE_GATEWAY_URL as string | undefined;
    const base = env && env.length > 0 ? env : `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws`;
    const sep = base.includes('?') ? '&' : '?';
    // walker: the token issued when the walk was created on this phone; room: the control-room token, if the server requires one
    const token = this.role === 'walker' ? walkCreds(this.walkId)?.token ?? '' : this.role === 'room' ? adminToken() : '';
    return `${base}${sep}walk=${encodeURIComponent(this.walkId)}&role=${this.role}${token ? `&token=${encodeURIComponent(token)}` : ''}`;
  }

  private setStatus(s: LinkStatus) {
    this.status = s;
    this.statusListeners.forEach((f) => f(s));
  }

  private connect() {
    if (this.closed) return;
    let ws: WebSocket;
    try {
      ws = new WebSocket(this.url());
    } catch {
      this.setStatus('local');
      return;
    }
    this.ws = ws;
    const giveUp = window.setTimeout(() => {
      if (ws.readyState !== WebSocket.OPEN) {
        this.setStatus('local');
      }
    }, 2500);
    ws.onopen = () => {
      window.clearTimeout(giveUp);
      this.retry = 0;
      this.setStatus('online');
      this.outbox.splice(0).forEach((m) => ws.send(m));
    };
    ws.onmessage = (ev) => {
      try {
        const data = JSON.parse(ev.data);
        if (data?.kind === 'history' && Array.isArray(data.envelopes)) data.envelopes.forEach((e: Envelope) => this.receive(e));
        else this.receive(data as Envelope);
      } catch {
        /* ignore malformed */
      }
    };
    ws.onclose = (ev) => {
      window.clearTimeout(giveUp);
      if (this.closed) return;
      if (ev.code === 4401 || ev.code === 4404 || ev.code === 1008) {
        // refused: wrong token or unknown walk. Retrying won't help.
        this.setStatus('local');
        return;
      }
      this.setStatus('local');
      const wait = Math.min(15000, 1000 * 2 ** this.retry++);
      window.setTimeout(() => this.connect(), wait);
    };
    ws.onerror = () => ws.close();
  }

  private receive(e: Envelope) {
    if (!e || !e.id || e.walkId !== this.walkId || this.seen.has(e.id)) return;
    this.seen.add(e.id);
    this.listeners.forEach((f) => f(e));
  }

  send<M extends Msg>(msg: M, from: Role = this.role): Envelope<M> {
    const env: Envelope<M> = { id: uid(), walkId: this.walkId, ts: Date.now(), from, msg };
    this.receive(env);
    const raw = JSON.stringify(env);
    this.bc?.postMessage(env);
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(raw);
    else if (this.status === 'connecting') this.outbox.push(raw);
    return env;
  }

  subscribe(f: Listener): () => void {
    this.listeners.add(f);
    return () => this.listeners.delete(f);
  }

  onStatus(f: (s: LinkStatus) => void): () => void {
    this.statusListeners.add(f);
    return () => this.statusListeners.delete(f);
  }

  close() {
    this.closed = true;
    this.ws?.close();
    this.bc?.close();
  }
}
