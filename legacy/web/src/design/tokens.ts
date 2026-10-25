// Mirrors tokens.css for code that needs raw values (MapLibre paint, canvas). Keep both in sync.
export const color = {
  bg: '#131a29', surface: '#1a2232', raise: '#222c40', line: '#2b3650', text: '#eceae3', muted: '#8b95a8',
  primary: '#7b8cf0', ok: '#5fcf9d', warn: '#e8975a', danger: '#ff6b5a', dayBg: '#f4f1ea', dayText: '#1b2030',
} as const
export const agentColor: Record<string, string> = { scout: '#7b8cf0', watcher: '#5fcf9d', rescuer: '#ff6b5a', reporter: '#e8975a', auditor: '#b08cf0', place: '#5fcf9d' }
