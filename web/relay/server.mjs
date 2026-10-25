// Dev relay: one WebSocket room per walk id. Forwards every envelope to everyone
// else in the room and replays recent history to late joiners (e.g. a judge who
// scans the QR mid-walk). The FastAPI gateway can replace this 1:1 — same wire format.
//
//   npm run relay            # ws://localhost:8787/ws?walk=demo&role=walker
//   PORT=9000 npm run relay
import { WebSocketServer } from 'ws';
import http from 'node:http';

const PORT = Number(process.env.PORT || 8787);
const HISTORY = 400;
const rooms = new Map(); // walkId -> { clients:Set<ws>, history:[] }

const server = http.createServer((req, res) => {
  if (req.url === '/health') {
    res.writeHead(200, { 'content-type': 'application/json' });
    res.end(JSON.stringify({ ok: true, rooms: [...rooms].map(([id, r]) => ({ id, clients: r.clients.size, messages: r.history.length })) }));
    return;
  }
  res.writeHead(404).end();
});

const wss = new WebSocketServer({ server, path: '/ws' });

wss.on('connection', (ws, req) => {
  const url = new URL(req.url, 'http://x');
  const walk = url.searchParams.get('walk') || 'demo';
  const role = url.searchParams.get('role') || 'unknown';
  let room = rooms.get(walk);
  if (!room) rooms.set(walk, (room = { clients: new Set(), history: [] }));
  room.clients.add(ws);
  console.log(`[relay] ${role} joined ${walk} (${room.clients.size} in room)`);

  // A new walk.start resets history so a fresh demo doesn't replay the last one.
  if (room.history.length) ws.send(JSON.stringify({ kind: 'history', envelopes: room.history }));

  ws.on('message', (buf) => {
    let env;
    try {
      env = JSON.parse(buf.toString());
    } catch {
      return;
    }
    if (!env || env.walkId !== walk || !env.msg) return;
    if (env.msg.type === 'walk.reset') room.history = room.history.filter((e) => e.msg.type === 'place.update' || e.msg.type === 'guardian.join');
    if (env.msg.type === 'walk.start') room.history = room.history.filter((e) => e.msg.type === 'agent.log' || e.msg.type === 'walk.plan' || e.msg.type === 'place.update' || e.msg.type === 'guardian.join');
    // positions are frequent: keep only the latest in history
    if (env.msg.type === 'walk.position') room.history = room.history.filter((e) => e.msg.type !== 'walk.position');
    room.history.push(env);
    if (room.history.length > HISTORY) room.history.splice(0, room.history.length - HISTORY);
    const raw = JSON.stringify(env);
    for (const c of room.clients) if (c !== ws && c.readyState === 1) c.send(raw);
  });

  ws.on('close', () => {
    room.clients.delete(ws);
    console.log(`[relay] ${role} left ${walk} (${room.clients.size} in room)`);
  });
});

server.listen(PORT, () => console.log(`[relay] listening on ws://localhost:${PORT}/ws`));
