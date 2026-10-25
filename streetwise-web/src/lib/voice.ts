// Voice I/O for the walker.
// Default speaker/listener use the browser's speech APIs — the stopgap in the build doc.
// The Voice teammate swaps in Cartesia (Ink in, Sonic out via the gateway) with
// setSpeaker() / setListenerFactory() without touching any screen code.

export type Intent = 'fine' | 'help';
export type Speaker = { speak: (text: string) => Promise<void>; stop: () => void };
export type ListenerHandle = { stop: () => void };
export type ListenerFactory = (onIntent: (i: Intent, transcript: string) => void, onSpeech: () => void) => ListenerHandle | null;

let audioCtx: AudioContext | null = null;

/** Call inside the first user tap ("Walk with me"): browsers block audio until then. */
export function unlockAudio() {
  try {
    const AC = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
    if (AC && !audioCtx) audioCtx = new AC();
    void audioCtx?.resume();
    if ('speechSynthesis' in window) {
      const u = new SpeechSynthesisUtterance(' ');
      u.volume = 0;
      speechSynthesis.speak(u);
    }
  } catch {
    /* no audio */
  }
}

export function getAudioContext() {
  return audioCtx;
}

function pickVoice(): SpeechSynthesisVoice | undefined {
  const voices = speechSynthesis.getVoices();
  const pref = ['Samantha', 'Google US English', 'Microsoft Aria', 'Karen', 'Daniel'];
  return voices.find((v) => pref.some((p) => v.name.includes(p))) ?? voices.find((v) => v.lang.startsWith('en'));
}

const browserSpeaker: Speaker = {
  speak(text) {
    return new Promise((resolve) => {
      if (!('speechSynthesis' in window)) return resolve();
      speechSynthesis.cancel();
      const u = new SpeechSynthesisUtterance(text);
      const v = pickVoice();
      if (v) u.voice = v;
      u.rate = 1.02;
      u.pitch = 1;
      u.onend = () => resolve();
      u.onerror = () => resolve();
      speechSynthesis.speak(u);
    });
  },
  stop() {
    if ('speechSynthesis' in window) speechSynthesis.cancel();
  },
};

// Cartesia Sonic through the gateway (the key stays on the server). Any failure falls back to on-device speech for that line.
let current: HTMLAudioElement | null = null;
const cartesiaSpeaker: Speaker = {
  async speak(text) {
    try {
      const r = await fetch('/api/voice/tts', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text }) });
      if (!r.ok) throw new Error(String(r.status));
      const url = URL.createObjectURL(await r.blob());
      current?.pause();
      current = new Audio(url);
      await new Promise<void>((resolve) => {
        current!.onended = () => resolve();
        current!.onerror = () => resolve();
        current!.play().catch(() => resolve());
      });
      URL.revokeObjectURL(url);
    } catch {
      await browserSpeaker.speak(text);
    }
  },
  stop() {
    current?.pause();
    browserSpeaker.stop();
  },
};

/** Pick the voice once at start-up: Cartesia when the gateway has it, otherwise the browser's own speech. */
export async function initVoice() {
  try {
    const h = (await fetch('/api/health').then((r) => r.json())) as { tts?: string };
    if (h.tts === 'cartesia') setSpeaker(cartesiaSpeaker);
  } catch {
    /* offline: browser speech */
  }
}

let speaker: Speaker = browserSpeaker;
let muted = false;

export function setSpeaker(s: Speaker) {
  speaker = s;
}
export function setMuted(m: boolean) {
  muted = m;
  if (m) speaker.stop();
}
export function isMuted() {
  return muted;
}
export function speak(text: string) {
  if (muted) return Promise.resolve();
  return speaker.speak(text);
}
export function stopSpeaking() {
  speaker.stop();
}

// ---------------------------------------------------------------- listening
const FINE = /\b(i'?m (fine|ok|okay|good|alright)|fine|okay|ok|all good|yes|yeah|good)\b/i;
const HELP = /\b(help|no|not okay|not ok|scared|emergency)\b/i;

export function parseIntent(t: string): Intent | null {
  if (HELP.test(t) && !/\bno problem\b/i.test(t)) return 'help';
  if (FINE.test(t)) return 'fine';
  return null;
}

type SR = {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  start: () => void;
  stop: () => void;
  onresult: ((e: { resultIndex: number; results: ArrayLike<ArrayLike<{ transcript: string }> & { isFinal: boolean }> }) => void) | null;
  onspeechstart: (() => void) | null;
  onend: (() => void) | null;
  onerror: (() => void) | null;
};

const browserListener: ListenerFactory = (onIntent, onSpeech) => {
  const Ctor = (window as unknown as { SpeechRecognition?: new () => SR; webkitSpeechRecognition?: new () => SR }).SpeechRecognition ??
    (window as unknown as { webkitSpeechRecognition?: new () => SR }).webkitSpeechRecognition;
  if (!Ctor) return null;
  let active = true;
  const rec = new Ctor();
  rec.continuous = true;
  rec.interimResults = true;
  rec.lang = 'en-US';
  rec.onspeechstart = () => onSpeech();
  rec.onresult = (e) => {
    for (let i = e.resultIndex; i < e.results.length; i++) {
      const r = e.results[i];
      const t = r[0].transcript;
      onSpeech();
      const intent = parseIntent(t);
      if (intent && r.isFinal) onIntent(intent, t);
    }
  };
  rec.onend = () => {
    if (active) {
      try {
        rec.start();
      } catch {
        /* already started */
      }
    }
  };
  rec.onerror = () => undefined;
  try {
    rec.start();
  } catch {
    return null;
  }
  return {
    stop() {
      active = false;
      try {
        rec.stop();
      } catch {
        /* noop */
      }
    },
  };
};

let listenerFactory: ListenerFactory = browserListener;
export function setListenerFactory(f: ListenerFactory) {
  listenerFactory = f;
}

/** Start listening for "I'm fine" / "help". Speaking over the app stops playback (barge-in). */
export function listen(onIntent: (i: Intent, transcript: string) => void): ListenerHandle | null {
  return listenerFactory(onIntent, () => stopSpeaking());
}

export const canListen = () =>
  typeof window !== 'undefined' && ('SpeechRecognition' in window || 'webkitSpeechRecognition' in window);
