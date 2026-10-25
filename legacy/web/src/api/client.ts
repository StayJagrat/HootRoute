import type { AgentEvent } from './types'

const base = ''
export async function api<T>(path: string, init?: RequestInit & { json?: unknown }): Promise<T> {
  const { json, ...rest } = init || {}
  const r = await fetch(base + path, { ...rest, headers: { 'content-type': 'application/json', ...(rest.headers || {}) }, body: json !== undefined ? JSON.stringify(json) : rest.body })
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`)
  return r.json() as Promise<T>
}

/** Subscribe to the agent trace of a session (or `walk-<id>` for a walk). Reconnects quietly. */
export function subscribe(session: string, onEvent: (e: AgentEvent) => void): () => void {
  let closed = false, ws: WebSocket | null = null, retry = 0
  const open = () => {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    ws = new WebSocket(`${proto}://${location.host}/ws/${session}`)
    ws.onmessage = (m) => { try { onEvent(JSON.parse(m.data)) } catch { /* ignore */ } }
    ws.onclose = () => { if (!closed) setTimeout(open, Math.min(4000, 400 * ++retry)) }
    ws.onopen = () => { retry = 0 }
  }
  open()
  return () => { closed = true; ws?.close() }
}
