/** Shared pieces for Assist screens (phone and web). Same CSS variables as Phase 0/2. */
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { CheckIcon, ShieldIcon, Spinner } from '../capture/ui';
import type { AnswerParts, Item, Label, Source, Stage } from './assistApi';

export const LABEL_TONE: Record<Label, { bg: string; fg: string; tint: string }> = {
  E: { bg: 'var(--green)', fg: 'var(--white)', tint: 'var(--green-tint)' },
  M: { bg: 'var(--manual)', fg: 'var(--white)', tint: 'var(--manual-tint)' },
  H: { bg: 'var(--history)', fg: 'var(--white)', tint: 'var(--history-tint)' },
};

const labelOf = (ref: string) => (ref[0]?.toUpperCase() as Label) ?? 'M';

/** [E1] chip: tap to open the source. */
export function SourceChip({ refId, source, onOpen }: { refId: string; source?: Source; onOpen?: (s: Source) => void }) {
  const { t } = useTranslation();
  const tone = LABEL_TONE[labelOf(refId)] ?? LABEL_TONE.M;
  return (
    <button type="button" disabled={!source || !onOpen} onClick={() => source && onOpen?.(source)}
      aria-label={t('assist.source.open', { ref: refId, title: source?.title ?? '' })}
      className="mx-0.5 inline-flex h-6 min-w-[2rem] items-center justify-center rounded-full px-2 align-middle text-xs font-bold leading-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ink)] disabled:opacity-60"
      style={{ background: tone.bg, color: tone.fg, fontFamily: 'var(--font-heading)' }}>
      {refId}
    </button>
  );
}

function Refs({ item, byRef, onOpen }: { item: Item; byRef: Map<string, Source>; onOpen?: (s: Source) => void }) {
  return <>{item.refs.map((r) => <SourceChip key={r} refId={r} source={byRef.get(r)} onOpen={onOpen} />)}</>;
}

/** The answer: safety first, numbered steps with source chips, then how to check. */
export function AnswerView({ parts, sources, onOpenSource, streaming = false }:
  { parts: AnswerParts; sources: Source[]; onOpenSource?: (s: Source) => void; streaming?: boolean }) {
  const { t } = useTranslation();
  const byRef = new Map(sources.map((s) => [s.ref, s]));
  return (
    <div className="space-y-3" aria-live={streaming ? 'polite' : undefined} aria-busy={streaming}>
      {parts.safety.map((s, i) => (
        <div key={`s${i}`} className="flex gap-3 rounded-2xl border border-[var(--safety)] bg-[var(--safety-tint)] px-4 py-3">
          <ShieldIcon />
          <p className="leading-relaxed"><b className="mr-1">{t('assist.answer.safety')}</b>{s.text} <Refs item={s} byRef={byRef} onOpen={onOpenSource} /></p>
        </div>
      ))}
      {parts.steps.length > 0 && (
        <ol className="space-y-2">
          {parts.steps.map((s, i) => (
            <li key={`p${i}`} className="flex gap-3 rounded-2xl bg-[var(--white)] px-4 py-3">
              <span className="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-[var(--green-tint)] text-sm font-bold text-[var(--green-deep)]"
                style={{ fontFamily: 'var(--font-heading)' }} aria-hidden="true">{s.n ?? i + 1}</span>
              <p className="text-[17px] leading-relaxed">
                <span className="sr-only">{t('assist.answer.step', { n: s.n ?? i + 1 })} </span>
                {s.text} <Refs item={s} byRef={byRef} onOpen={onOpenSource} />
              </p>
            </li>
          ))}
        </ol>
      )}
      {parts.check && (
        <div className="flex gap-3 rounded-2xl bg-[var(--green-tint)] px-4 py-3 text-[var(--green-deep)]">
          <span className="mt-0.5"><CheckIcon /></span>
          <p className="leading-relaxed"><b className="mr-1">{t('assist.answer.check')}</b>{parts.check.text} <Refs item={parts.check} byRef={byRef} onOpen={onOpenSource} /></p>
        </div>
      )}
      {streaming && <span className="inline-block h-5 w-2 animate-pulse rounded-sm bg-[var(--green)] align-middle motion-reduce:animate-none" aria-hidden="true" />}
    </div>
  );
}

/** The list of sources under an answer. Used ones first. */
export function SourceList({ sources, used, onOpen }: { sources: Source[]; used: string[]; onOpen: (s: Source) => void }) {
  const { t } = useTranslation();
  const list = [...sources].sort((a, b) => Number(used.includes(b.ref)) - Number(used.includes(a.ref)));
  if (!list.length) return null;
  return (
    <section aria-label={t('assist.source.title')}>
      <h2 className="mb-2 text-sm font-semibold text-[var(--ink-muted)]">{t('assist.source.title')}</h2>
      <ul className="space-y-2">
        {list.map((s) => {
          const tone = LABEL_TONE[s.label] ?? LABEL_TONE.M;
          return (
            <li key={s.ref}>
              <button type="button" onClick={() => onOpen(s)}
                className={`flex w-full items-start gap-3 rounded-2xl px-3 py-2.5 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--green)] ${used.includes(s.ref) ? 'bg-[var(--white)]' : 'bg-[var(--surface)] opacity-80'}`}>
                <span className="mt-0.5 inline-flex h-6 min-w-[2rem] items-center justify-center rounded-full px-2 text-xs font-bold"
                  style={{ background: tone.bg, color: tone.fg, fontFamily: 'var(--font-heading)' }}>{s.ref}</span>
                <span className="min-w-0 flex-1">
                  <span className="block text-sm font-semibold leading-snug"><span className="sr-only">{t(`assist.source.kind.${s.label}`)}: </span>{s.title}</span>
                  <span className="mt-0.5 line-clamp-2 block text-xs text-[var(--ink-muted)]">{s.snippet}</span>
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

const STAGES: Stage[] = ['listening', 'understanding', 'searching', 'writing'];

/** "Listening → Understanding → Searching → Writing" progress line. */
export function StageLine({ stage, voice }: { stage: Stage | null; voice: boolean }) {
  const { t } = useTranslation();
  const steps = STAGES.filter((s) => voice || s !== 'listening');
  const current = stage === 'queued' ? -1 : steps.indexOf(stage as Stage);
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm" aria-live="polite">
      {stage === 'queued' && <span className="inline-flex items-center gap-2 text-[var(--ink-muted)]"><Spinner size={14} />{t('assist.stage.queued')}</span>}
      {steps.map((s, i) => (
        <span key={s} className={`inline-flex items-center gap-1.5 ${i < current ? 'text-[var(--green-deep)]' : i === current ? 'font-semibold text-[var(--ink)]' : 'text-[var(--ink-faint)]'}`}>
          {i < current ? <CheckIcon /> : i === current ? <Spinner size={14} /> : <span className="h-2 w-2 rounded-full bg-current" aria-hidden="true" />}
          {t(`assist.stage.${s}`)}
        </span>
      ))}
    </div>
  );
}

/** Tiny audio player: play/pause + progress. Works for webm files with unknown duration. */
export function AudioMini({ src, label }: { src: string; label: string }) {
  const { t } = useTranslation();
  const ref = useRef<HTMLAudioElement | null>(null);
  const [playing, setPlaying] = useState(false);
  const [progress, setProgress] = useState(0);
  useEffect(() => () => ref.current?.pause(), []);
  const toggle = () => {
    const a = ref.current;
    if (!a) return;
    if (a.paused) a.play().catch(() => setPlaying(false));
    else a.pause();
  };
  return (
    <div className="flex items-center gap-3 rounded-full bg-[var(--ink)] px-2 py-1.5 text-[var(--white)]">
      <button type="button" onClick={toggle} aria-label={playing ? t('assist.audio.pause') : t('assist.audio.play', { label })}
        className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-[var(--white)] text-[var(--ink)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--safety)]">
        {playing ? (
          <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><rect x="5" y="4" width="5" height="16" rx="1" /><rect x="14" y="4" width="5" height="16" rx="1" /></svg>
        ) : (
          <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M7 4.5v15l13-7.5z" /></svg>
        )}
      </button>
      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-white/25"><div className="h-full bg-[var(--safety)]" style={{ width: `${progress * 100}%` }} /></div>
      <span className="pr-2 text-xs opacity-80">{label}</span>
      <audio ref={ref} src={src} preload="metadata"
        onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)} onEnded={() => { setPlaying(false); setProgress(0); }}
        onTimeUpdate={(e) => {
          const a = e.currentTarget;
          if (Number.isFinite(a.duration) && a.duration > 0) setProgress(a.currentTime / a.duration);
        }} />
    </div>
  );
}

/** Bottom sheet (phone) / side panel feel (web). Esc and the backdrop close it. */
export function Sheet({ open, onClose, title, children }: { open: boolean; onClose: () => void; title: ReactNode; children: ReactNode }) {
  const { t } = useTranslation();
  const closeRef = useRef<HTMLButtonElement | null>(null);
  useEffect(() => {
    if (!open) return;
    closeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center sm:items-center" role="dialog" aria-modal="true">
      <button type="button" aria-label={t('assist.close')} className="absolute inset-0 bg-black/40" onClick={onClose} tabIndex={-1} />
      <div className="relative max-h-[88dvh] w-full max-w-[560px] overflow-y-auto rounded-t-[28px] bg-[var(--bg-enamel)] p-4 pb-6 text-[var(--ink)] shadow-xl sm:rounded-[28px]"
        style={{ fontFamily: 'var(--font-body)' }}>
        <div className="mb-3 flex items-start gap-3">
          <div className="min-w-0 flex-1 text-lg font-semibold leading-snug" style={{ fontFamily: 'var(--font-heading)' }}>{title}</div>
          <button ref={closeRef} type="button" onClick={onClose} aria-label={t('assist.close')}
            className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-[var(--surface)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--green)]">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" /></svg>
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

export function Notice({ tone = 'info', children }: { tone?: 'info' | 'alert' | 'ok'; children: ReactNode }) {
  const cls = tone === 'alert' ? 'bg-[var(--alert-tint)] text-[var(--alert)]'
    : tone === 'ok' ? 'bg-[var(--green-tint)] text-[var(--green-deep)]' : 'bg-[var(--surface)] text-[var(--ink-muted)]';
  return <div role={tone === 'alert' ? 'alert' : 'status'} className={`rounded-2xl px-4 py-3 text-sm ${cls}`}>{children}</div>;
}

export function ago(iso: string | null | undefined, lang: string) {
  if (!iso) return '';
  const mins = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
  const rtf = new Intl.RelativeTimeFormat(lang, { numeric: 'auto' });
  if (mins < 60) return rtf.format(-mins, 'minute');
  if (mins < 60 * 24) return rtf.format(-Math.round(mins / 60), 'hour');
  return rtf.format(-Math.round(mins / 1440), 'day');
}
