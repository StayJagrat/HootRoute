// Browser voice: speech synthesis for the Watcher, speech recognition for "I'm fine" / "help". Both are optional.
// SpeechRecognition support varies (Chrome yes, iOS Safari partial), so tap buttons are always the reliable path.
type Rec = { start(): void; stop(): void; onresult: ((e: any) => void) | null; onend: (() => void) | null; onerror: ((e: any) => void) | null; continuous: boolean; interimResults: boolean; lang: string }
const Ctor: (new () => Rec) | undefined = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition
export const voiceSupported = !!Ctor

export function speak(text: string) {
  try { if (!('speechSynthesis' in window) || !text) return; speechSynthesis.cancel(); const u = new SpeechSynthesisUtterance(text); u.rate = 1.02; u.pitch = 1; speechSynthesis.speak(u) } catch { /* optional */ }
}

export function listen(onFine: () => void, onHelp: () => void): () => void {
  if (!Ctor) return () => {}
  let stopped = false; const r = new Ctor(); r.continuous = true; r.interimResults = false; r.lang = 'en-US'
  r.onresult = (e: any) => {
    const t = String(e.results[e.results.length - 1][0].transcript || '').toLowerCase()
    if (/\b(help|emergency)\b/.test(t)) onHelp(); else if (/\b(i'?m fine|im fine|all good|okay|i'?m ok)\b/.test(t)) onFine()
  }
  r.onend = () => { if (!stopped) { try { r.start() } catch { /* already started */ } } }
  r.onerror = () => { /* permission denied or unsupported: buttons still work */ }
  try { r.start() } catch { /* ignore */ }
  return () => { stopped = true; try { r.stop() } catch { /* ignore */ } }
}
