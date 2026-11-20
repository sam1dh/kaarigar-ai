/**
 * Speech output helpers shared by Read aloud and voice mode.
 *
 * Browsers only allow sound after a tap. `primeSpeech()` is called inside the tap that stops the recording,
 * so the answer can start speaking a few seconds later without another tap.
 */

// 44-byte silent WAV: playing it during the tap unlocks the shared <audio> element on Android Chrome / iOS Safari.
const SILENT_WAV = 'data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEARKwAAIhYAQACABAAZGF0YQAAAAA=';
let shared: HTMLAudioElement | null = null;

export const canSpeak = () => typeof window !== 'undefined' && 'speechSynthesis' in window;

export function sharedAudio(): HTMLAudioElement {
  if (!shared) shared = new Audio();
  return shared;
}

/** Call inside a tap handler (e.g. "stop recording"). Safe to call many times. */
export function primeSpeech() {
  try {
    if (canSpeak()) {
      const u = new SpeechSynthesisUtterance(' ');
      u.volume = 0;
      window.speechSynthesis.speak(u);
    }
  } catch {
    /* ignore */
  }
  try {
    const a = sharedAudio();
    a.src = SILENT_WAV;
    a.play().catch(() => undefined);
  } catch {
    /* ignore */
  }
}

/** A phone voice for this language (hi-IN, ta-IN …), or null if the phone has none. */
export function findVoice(lang: string): SpeechSynthesisVoice | null {
  if (!canSpeak()) return null;
  const voices = window.speechSynthesis.getVoices();
  const want = lang.toLowerCase();
  const base = want.split('-')[0];
  return voices.find((v) => v.lang.toLowerCase().replace('_', '-') === want)
    ?? voices.find((v) => v.lang.toLowerCase().replace('_', '-').startsWith(`${base}-`) || v.lang.toLowerCase() === base)
    ?? null;
}

/** Voices load late on some phones: resolves when the list is ready (or after 1 s). */
export function voicesReady(): Promise<void> {
  if (!canSpeak() || window.speechSynthesis.getVoices().length) return Promise.resolve();
  return new Promise((resolve) => {
    const done = () => {
      window.speechSynthesis.removeEventListener('voiceschanged', done);
      resolve();
    };
    window.speechSynthesis.addEventListener('voiceschanged', done);
    window.setTimeout(done, 1000);
  });
}
