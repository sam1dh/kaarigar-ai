import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { fmt } from './VoiceGauge';

interface Props { src: string; knownSeconds?: number | null; label?: string }

/** Design-system audio player. Fixes Chrome's MediaRecorder webm "Infinity" duration. */
export default function AudioPlayer({ src, knownSeconds, label }: Props) {
  const { t } = useTranslation();
  const ref = useRef<HTMLAudioElement>(null);
  const [playing, setPlaying] = useState(false);
  const [pos, setPos] = useState(0);
  const [dur, setDur] = useState(knownSeconds && knownSeconds > 0 ? knownSeconds : 0);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const a = ref.current;
    if (!a) return;
    setFailed(false);
    let fixing = false;
    const onMeta = () => {
      if (Number.isFinite(a.duration) && a.duration > 0) { setDur(a.duration); return; }
      if (knownSeconds && knownSeconds > 0) return; // we already know the length
      // webm from MediaRecorder: duration is Infinity until we seek far ahead once
      fixing = true;
      a.currentTime = 1e101;
    };
    const onTime = () => {
      if (fixing) {
        fixing = false;
        if (Number.isFinite(a.duration) && a.duration > 0) setDur(a.duration);
        a.currentTime = 0;
        return;
      }
      setPos(a.currentTime);
    };
    const onPlay = () => setPlaying(true);
    const onPause = () => setPlaying(false);
    const onEnd = () => { setPlaying(false); setPos(0); };
    const onErr = () => setFailed(true);
    a.addEventListener('loadedmetadata', onMeta);
    a.addEventListener('timeupdate', onTime);
    a.addEventListener('play', onPlay);
    a.addEventListener('pause', onPause);
    a.addEventListener('ended', onEnd);
    a.addEventListener('error', onErr);
    return () => {
      a.removeEventListener('loadedmetadata', onMeta);
      a.removeEventListener('timeupdate', onTime);
      a.removeEventListener('play', onPlay);
      a.removeEventListener('pause', onPause);
      a.removeEventListener('ended', onEnd);
      a.removeEventListener('error', onErr);
    };
  }, [src, knownSeconds]);

  const toggle = () => {
    const a = ref.current;
    if (!a) return;
    if (a.paused) a.play().catch(() => setFailed(true));
    else a.pause();
  };
  const shown = Math.min(pos, dur || pos);
  const pct = dur > 0 ? Math.min(100, (shown / dur) * 100) : 0;

  return (
    <div className="flex items-center gap-3 rounded-2xl bg-[var(--surface)] p-3">
      <audio ref={ref} src={src} preload="metadata" />
      <button type="button" onClick={toggle} disabled={failed}
        aria-label={playing ? t('capture.player.pause') : t('capture.player.play')}
        className="grid h-12 w-12 shrink-0 place-items-center rounded-full bg-[var(--green)] text-white
                   disabled:opacity-40 focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-[var(--green-tint)]">
        {playing ? (
          <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
            <rect x="6" y="5" width="4" height="14" rx="1" /><rect x="14" y="5" width="4" height="14" rx="1" />
          </svg>
        ) : (
          <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
            <path d="M8 5.5v13a1 1 0 0 0 1.5.86l10.5-6.5a1 1 0 0 0 0-1.72L9.5 4.64A1 1 0 0 0 8 5.5z" />
          </svg>
        )}
      </button>
      <div className="min-w-0 flex-1">
        <div className="mb-1.5 flex items-baseline justify-between gap-2 text-sm">
          <span className="truncate font-semibold">{failed ? t('capture.player.error') : label}</span>
          <span className="shrink-0 tabular-nums text-[var(--ink-muted)]"
            style={{ fontFamily: 'var(--font-heading)' }}>
            {fmt(shown)} / {fmt(dur)}
          </span>
        </div>
        <div className="relative h-2 rounded-full bg-[var(--line)]">
          <div className="absolute inset-y-0 left-0 rounded-full bg-[var(--green)]" style={{ width: `${pct}%` }} />
          <input type="range" min={0} max={dur || 0} step={0.1} value={shown} disabled={!dur || failed}
            aria-label={t('capture.player.seek')}
            onChange={(e) => { if (ref.current) ref.current.currentTime = Number(e.target.value); }}
            className="absolute inset-0 h-full w-full cursor-pointer opacity-0" />
        </div>
      </div>
    </div>
  );
}
