import { useCallback, useEffect, useRef, useState } from 'react';

export type RecorderState = 'idle' | 'requesting' | 'recording' | 'stopped' | 'error';
export type RecorderError = 'insecure' | 'unsupported' | 'denied' | 'no_mic' | 'failed';

const CANDIDATES = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/ogg;codecs=opus'];

function pickMime(): string {
  if (typeof MediaRecorder === 'undefined') return '';
  return CANDIDATES.find((t) => MediaRecorder.isTypeSupported?.(t)) ?? '';
}

/**
 * Microphone recorder for the Record screen.
 * - Picks a format the browser supports (webm/opus on Android Chrome, mp4/aac on iPhone Safari).
 * - `level` (0..1) drives the gauge needle.
 * - Stops by itself at `maxSec`.
 * Needs HTTPS (the Cloudflare tunnel) or localhost.
 */
export function useRecorder(maxSec = 180) {
  const [state, setState] = useState<RecorderState>('idle');
  const [error, setError] = useState<RecorderError | null>(null);
  const [seconds, setSeconds] = useState(0);
  const [level, setLevel] = useState(0);
  const [blob, setBlob] = useState<Blob | null>(null);
  const [mimeType, setMimeType] = useState('');

  const recRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const ctxRef = useRef<AudioContext | null>(null);
  const rafRef = useRef<number | null>(null);
  const timerRef = useRef<number | null>(null);
  const startedRef = useRef(0);
  const chunksRef = useRef<BlobPart[]>([]);

  const cleanup = useCallback(() => {
    if (rafRef.current) cancelAnimationFrame(rafRef.current);
    if (timerRef.current) window.clearInterval(timerRef.current);
    rafRef.current = null;
    timerRef.current = null;
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    ctxRef.current?.close().catch(() => undefined);
    ctxRef.current = null;
    setLevel(0);
  }, []);

  useEffect(() => cleanup, [cleanup]);

  const stop = useCallback(() => {
    const rec = recRef.current;
    if (rec && rec.state !== 'inactive') rec.stop();
  }, []);

  const start = useCallback(async () => {
    setError(null);
    setBlob(null);
    setSeconds(0);
    if (!window.isSecureContext) {
      setError('insecure');
      setState('error');
      return;
    }
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
      setError('unsupported');
      setState('error');
      return;
    }
    setState('requesting');
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
    } catch (e) {
      const name = (e as DOMException)?.name;
      setError(name === 'NotAllowedError' ? 'denied' : name === 'NotFoundError' ? 'no_mic' : 'failed');
      setState('error');
      return;
    }
    streamRef.current = stream;

    // Level meter for the gauge
    try {
      const Ctx = window.AudioContext || (window as any).webkitAudioContext;
      const ctx: AudioContext = new Ctx();
      ctxRef.current = ctx;
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 512;
      ctx.createMediaStreamSource(stream).connect(analyser);
      const buf = new Uint8Array(analyser.fftSize);
      const tick = () => {
        analyser.getByteTimeDomainData(buf);
        let sum = 0;
        for (let i = 0; i < buf.length; i++) {
          const v = (buf[i] - 128) / 128;
          sum += v * v;
        }
        const rms = Math.sqrt(sum / buf.length);
        setLevel((prev) => prev * 0.6 + Math.min(1, rms * 4) * 0.4);
        rafRef.current = requestAnimationFrame(tick);
      };
      tick();
    } catch {
      /* gauge just stays still */
    }

    const mime = pickMime();
    setMimeType(mime || 'audio/webm');
    const rec = mime ? new MediaRecorder(stream, { mimeType: mime }) : new MediaRecorder(stream);
    recRef.current = rec;
    chunksRef.current = [];
    rec.ondataavailable = (ev) => {
      if (ev.data && ev.data.size > 0) chunksRef.current.push(ev.data);
    };
    rec.onstop = () => {
      navigator.vibrate?.(30);
      const type = rec.mimeType || mime || 'audio/webm';
      setMimeType(type);
      setBlob(new Blob(chunksRef.current, { type }));
      setSeconds(Math.round((performance.now() - startedRef.current) / 100) / 10);
      setState('stopped');
      cleanup();
    };
    rec.start(1000);
    startedRef.current = performance.now();
    setState('recording');
    navigator.vibrate?.(30);
    timerRef.current = window.setInterval(() => {
      const s = (performance.now() - startedRef.current) / 1000;
      setSeconds(Math.floor(s));
      if (s >= maxSec) stop();
    }, 250);
  }, [cleanup, maxSec, stop]);

  const reset = useCallback(() => {
    stop();
    cleanup();
    setBlob(null);
    setSeconds(0);
    setError(null);
    setState('idle');
  }, [cleanup, stop]);

  return { state, error, seconds, level, blob, mimeType, start, stop, reset, maxSec };
}
