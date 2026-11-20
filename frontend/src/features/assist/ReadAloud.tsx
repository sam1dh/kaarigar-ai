/**
 * Read the answer aloud.
 * 1. The phone's own voice (speechSynthesis) when it has one for the language: instant and free.
 * 2. Otherwise Sarvam Bulbul through POST /assist/queries/:id/tts (cached on the server after the first play).
 */
import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Spinner } from '../capture/ui';
import { fetchSpeech, type AnswerParts } from './assistApi';
import { speakableText } from './parseAnswer';
import { findVoice, sharedAudio } from './speech';

export default function ReadAloud({ queryId, parts, lang }: { queryId: string; parts: AnswerParts; lang: string }) {
  const { t } = useTranslation();
  const [state, setState] = useState<'idle' | 'loading' | 'playing' | 'error'>('idle');
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const urlRef = useRef<string | null>(null);

  useEffect(() => {
    // Some browsers load voices late; asking once warms the list up.
    if ('speechSynthesis' in window) window.speechSynthesis.getVoices();
    return () => {
      if ('speechSynthesis' in window) window.speechSynthesis.cancel();
      audioRef.current?.pause();
      if (urlRef.current) URL.revokeObjectURL(urlRef.current);
    };
  }, []);

  const stop = () => {
    if ('speechSynthesis' in window) window.speechSynthesis.cancel();
    audioRef.current?.pause();
    setState('idle');
  };

  const play = async () => {
    const voice = findVoice(lang);
    if (voice) {
      const u = new SpeechSynthesisUtterance(speakableText(parts, { safety: t('assist.answer.safety'), check: t('assist.answer.check') }));
      u.voice = voice;
      u.lang = voice.lang;
      u.rate = 0.95;
      u.onend = () => setState('idle');
      u.onerror = () => setState('idle');
      window.speechSynthesis.cancel();
      window.speechSynthesis.speak(u);
      setState('playing');
      return;
    }
    try {
      setState('loading');
      if (!urlRef.current) urlRef.current = URL.createObjectURL(await fetchSpeech(queryId));
      const a = audioRef.current ?? sharedAudio();
      audioRef.current = a;
      a.src = urlRef.current;
      a.onended = () => setState('idle');
      await a.play();
      setState('playing');
    } catch {
      setState('error');
    }
  };

  return (
    <div>
      <button type="button" onClick={state === 'playing' ? stop : play} disabled={state === 'loading'}
        className="inline-flex min-h-[48px] items-center gap-2 rounded-full bg-[var(--ink)] px-5 font-semibold text-[var(--white)] focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-[var(--safety)] disabled:opacity-60">
        {state === 'loading' ? <Spinner /> : state === 'playing' ? (
          <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><rect x="6" y="6" width="12" height="12" rx="2" /></svg>
        ) : (
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M11 5L6 9H3v6h3l5 4V5z" /><path d="M15.5 8.5a5 5 0 0 1 0 7M18.5 5.5a9 9 0 0 1 0 13" />
          </svg>
        )}
        {state === 'playing' ? t('assist.read.stop') : t('assist.read.play')}
      </button>
      {state === 'error' && <p role="alert" className="mt-2 text-sm text-[var(--alert)]">{t('assist.errors.tts_failed')}</p>}
    </div>
  );
}
