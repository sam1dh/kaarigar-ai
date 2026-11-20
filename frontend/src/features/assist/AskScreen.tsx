/**
 * 03 Ask (/tech/machines/:code/ask, or /tech/ask for "any machine").
 * Tap the gauge, say what's wrong, tap again: the answer streams in, with source chips, read aloud,
 * "Did this fix it?" and "Ask an expert". Typing is the fallback (noisy floor, no mic).
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate, useParams } from 'react-router-dom';
import { useRecorder } from '../capture/useRecorder';
import VoiceGauge from '../capture/VoiceGauge';
import { BigButton, Card, MachineChip, Screen, Spinner, TopBar } from '../capture/ui';
import AfterAnswer from './AfterAnswer';
import type { AskInput, Source } from './assistApi';
import { parseAnswerText } from './parseAnswer';
import { AnswerView, Notice, SourceList, StageLine } from './parts';
import ReadAloud from './ReadAloud';
import SourceSheet from './SourceSheet';
import { primeSpeech } from './speech';
import { useAsk } from './useAsk';
import { useAutoStop } from './useAutoStop';
import { useSpokenAnswer } from './useSpokenAnswer';

const MAX_SEC = 60;
const MIN_SEC = 1;
const AUTO_SPEAK_KEY = 'kaarigar.autoSpeak';
const VAD_KEY = 'kaarigar.autoSend';

function readFlag(key: string, fallback: boolean) {
  try {
    const v = window.localStorage.getItem(key);
    return v === null ? fallback : v === '1';
  } catch {
    return fallback;
  }
}

export default function AskScreen() {
  const { code } = useParams();
  const nav = useNavigate();
  const { t, i18n } = useTranslation();
  const rec = useRecorder(MAX_SEC);
  const { state, ask, reset } = useAsk();
  const [typing, setTyping] = useState(false);
  const [text, setText] = useState('');
  const [openSource, setOpenSource] = useState<Source | null>(null);
  const lastInput = useRef<AskInput | null>(null);
  const sentBlob = useRef<Blob | null>(null);
  const [autoSpeak, setAutoSpeak] = useState(() => readFlag(AUTO_SPEAK_KEY, true));
  const toggleAutoSpeak = (on: boolean) => {
    setAutoSpeak(on);
    try { window.localStorage.setItem(AUTO_SPEAK_KEY, on ? '1' : '0'); } catch { /* private mode */ }
  };
  const [autoSend, setAutoSend] = useState(() => readFlag(VAD_KEY, true));
  const toggleAutoSend = (on: boolean) => {
    setAutoSend(on);
    try { window.localStorage.setItem(VAD_KEY, on ? '1' : '0'); } catch { /* private mode */ }
  };
  const [heardNothing, setHeardNothing] = useState(false);
  // VAD: the question is sent by itself when the person stops talking
  const vad = useAutoStop(rec, autoSend && !typing, () => setHeardNothing(true));

  const recording = rec.state === 'recording';
  const tooShort = rec.state === 'stopped' && rec.seconds < MIN_SEC;

  // A finished recording is sent straight away: no listen-back step for questions.
  useEffect(() => {
    if (rec.state === 'stopped' && rec.blob && !tooShort && sentBlob.current !== rec.blob) {
      sentBlob.current = rec.blob;
      const input: AskInput = { machineCode: code, audio: { blob: rec.blob, mimeType: rec.mimeType } };
      lastInput.current = input;
      ask(input);
    }
  }, [rec.state, rec.blob, rec.mimeType, tooShort, code, ask]);

  const submitText = () => {
    const q = text.trim();
    if (q.length < 3) return;
    const input: AskInput = { machineCode: code, text: q };
    lastInput.current = input;
    ask(input);
  };

  const again = () => {
    spoken.stop();
    reset();
    rec.reset();
    sentBlob.current = null;
    setText('');
    setHeardNothing(false);
  };

  /** Interrupt: stop the voice and the answer still streaming, and start listening right away. */
  const interrupt = () => {
    primeSpeech();
    again();
    setTyping(false);
    void rec.start();
  };

  const live = useMemo(() => parseAnswerText(state.text), [state.text]);
  const parts = state.parts ?? live;
  const showAnswer = (state.phase === 'streaming' && state.text) || (state.phase === 'done' && state.status === 'answered');
  const voice = lastInput.current?.audio !== undefined;
  const idle = state.phase === 'idle';
  const words = useMemo(() => ({ safety: t('assist.answer.safety'), check: t('assist.answer.check') }), [t]);
  // Voice in -> voice out: a spoken question gets a spoken answer (unless switched off)
  const spoken = useSpokenAnswer({
    enabled: voice && autoSpeak, lang: i18n.language, text: state.text, phase: state.phase, status: state.status,
    queryId: state.queryId, words, noAnswerText: t('assist.answer.noAnswer'),
  });

  return (
    <Screen>
      <TopBar onBack={() => nav(code ? `/tech/machines/${encodeURIComponent(code)}` : '/tech')} title={t('assist.ask.title')}
        right={code ? <MachineChip code={code} /> : undefined} />

      {idle && (
        <>
          <Card className="mb-6">
            <p className="font-semibold">{t('assist.ask.prompt')}</p>
            <p className="mt-1 text-sm text-[var(--ink-muted)]">{t('assist.ask.example')}</p>
          </Card>

          {!typing ? (
            <>
              <VoiceGauge recording={recording} level={rec.level} seconds={rec.seconds} maxSec={MAX_SEC}
                disabled={rec.state === 'requesting'} label={recording ? t('assist.ask.stop') : t('assist.ask.start')}
                onPress={() => {
                  primeSpeech();            // a tap is what lets the answer speak by itself later
                  setHeardNothing(false);
                  if (recording) rec.stop();
                  else rec.start();
                }} />
              <p className="mt-4 text-center text-sm text-[var(--ink-muted)]" aria-live="polite">
                {!recording ? t('assist.ask.tapToStart')
                  : !autoSend ? t('assist.ask.tapToStop')
                  : vad === 'speaking' ? t('assist.vad.hearing') : t('assist.vad.waiting')}
              </p>
              {heardNothing && <div className="mt-4"><Notice>{t('assist.vad.heardNothing')}</Notice></div>}
              <div className="mt-5 space-y-2">
                <label className="flex items-center gap-3 text-sm">
                  <input type="checkbox" checked={autoSend} onChange={(e) => toggleAutoSend(e.target.checked)}
                    className="h-5 w-5 shrink-0 accent-[var(--green)]" />
                  <span>{t('assist.vad.autoSend')}</span>
                </label>
                <label className="flex items-center gap-3 text-sm">
                  <input type="checkbox" checked={autoSpeak} onChange={(e) => toggleAutoSpeak(e.target.checked)}
                    className="h-5 w-5 shrink-0 accent-[var(--green)]" />
                  <span>{t('assist.voice.autoSpeak')}</span>
                </label>
              </div>
              {tooShort && <div className="mt-4"><Notice tone="alert">{t('assist.errors.too_short')}</Notice></div>}
              {rec.state === 'error' && rec.error && (
                <div className="mt-4"><Notice tone="alert">{t(`capture.record.errors.${rec.error}`)}</Notice></div>
              )}
              <div className="mt-auto pt-6">
                <BigButton kind="secondary" onClick={() => { rec.reset(); setTyping(true); }} disabled={recording}>
                  {t('assist.ask.typeInstead')}
                </BigButton>
              </div>
            </>
          ) : (
            <form className="flex flex-1 flex-col" onSubmit={(e) => { e.preventDefault(); submitText(); }}>
              <label htmlFor="ask-text" className="mb-2 text-sm font-semibold">{t('assist.ask.typeLabel')}</label>
              <textarea id="ask-text" value={text} onChange={(e) => setText(e.target.value.slice(0, 500))} rows={4} autoFocus
                lang={i18n.language} placeholder={t('assist.ask.typePlaceholder')}
                className="w-full rounded-2xl border border-[var(--line)] bg-[var(--white)] p-4 text-[17px] leading-relaxed focus:outline-none focus:ring-2 focus:ring-[var(--green)]" />
              <div className="mt-auto space-y-3 pt-6">
                <BigButton type="submit" disabled={text.trim().length < 3}>{t('assist.ask.send')}</BigButton>
                <BigButton kind="secondary" onClick={() => setTyping(false)}>{t('assist.ask.speakInstead')}</BigButton>
              </div>
            </form>
          )}
        </>
      )}

      {!idle && (
        <div className="flex flex-1 flex-col gap-4">
          {/* You asked */}
          <div className="self-end max-w-[85%] rounded-[22px] rounded-br-md bg-[var(--green)] px-4 py-3 text-[var(--white)]">
            <div className="text-xs opacity-80">{t('assist.ask.youAsked')}</div>
            <div className="text-[17px] leading-snug">
              {state.question?.original ?? (lastInput.current?.text || <span className="inline-flex items-center gap-2"><Spinner size={14} />{t('assist.stage.listening')}</span>)}
            </div>
          </div>

          {state.phase === 'streaming' && <StageLine stage={state.stage} voice={voice} />}

          {spoken.speaking && (
            <div className="sticky top-2 z-10 flex items-center justify-between gap-3 rounded-full bg-[var(--ink)] py-1.5 pl-4 pr-1.5 text-[var(--white)]" role="status">
              <span className="inline-flex items-center gap-2 text-sm font-semibold">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <path d="M11 5L6 9H3v6h3l5 4V5z" /><path d="M15.5 8.5a5 5 0 0 1 0 7M18.5 5.5a9 9 0 0 1 0 13" />
                </svg>
                {t('assist.voice.speaking')}
              </span>
              <button type="button" onClick={spoken.stop}
                className="min-h-[40px] rounded-full bg-[var(--white)] px-4 text-sm font-semibold text-[var(--ink)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--safety)]">
                {t('assist.voice.stop')}
              </button>
            </div>
          )}

          {showAnswer && (
            <AnswerView parts={parts} sources={state.sources} onOpenSource={setOpenSource} streaming={state.phase === 'streaming'} />
          )}

          {state.phase === 'done' && state.status === 'no_answer' && (
            <Notice>{code ? t('assist.answer.noAnswerMachine', { code }) : t('assist.answer.noAnswer')}</Notice>
          )}

          {state.phase === 'error' && (
            <Notice tone="alert">{t(`assist.errors.${state.error?.code}`, { defaultValue: t('assist.errors.internal') })}</Notice>
          )}

          {state.phase === 'done' && state.status === 'answered' && state.queryId && !spoken.speaking && (
            <ReadAloud queryId={state.queryId} parts={parts} lang={i18n.language} />
          )}

          {state.queryId && (state.phase === 'done' || (state.phase === 'error' && state.error?.code !== 'network')) && (
            <AfterAnswer queryId={state.queryId} status={state.phase === 'error' ? 'failed' : (state.status ?? 'answered')}
              suggestEscalate={state.suggestEscalate} />
          )}

          {state.phase === 'done' && state.status === 'answered' && (
            <SourceList sources={state.sources} used={parts.refs_used} onOpen={setOpenSource} />
          )}

          {(state.phase === 'error' || state.phase === 'done') && (
            <div className="space-y-3">
              {state.phase === 'error' && lastInput.current && (
                <BigButton kind="secondary" onClick={() => lastInput.current && ask(lastInput.current)}>{t('assist.ask.retry')}</BigButton>
              )}
              <BigButton kind="secondary" onClick={() => { again(); setTyping(true); }}>{t('assist.ask.typeInstead')}</BigButton>
            </div>
          )}

          {/* Interrupt: always within thumb reach, works while the answer is streaming or being spoken */}
          <div className="sticky bottom-0 mt-auto bg-gradient-to-t from-[var(--bg-enamel)] from-70% to-transparent pb-1 pt-4">
            <BigButton onClick={interrupt}>
              <span className="inline-flex items-center justify-center gap-2">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
                  <rect x="9" y="3" width="6" height="11" rx="3" /><path d="M5 11a7 7 0 0 0 14 0M12 18v3" />
                </svg>
                {state.phase === 'streaming' || spoken.speaking ? t('assist.interrupt.now') : t('assist.interrupt.again')}
              </span>
            </BigButton>
          </div>
        </div>
      )}

      <SourceSheet source={openSource} onClose={() => setOpenSource(null)} />
    </Screen>
  );
}
