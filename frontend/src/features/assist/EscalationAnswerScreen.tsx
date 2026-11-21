/**
 * 10 Answer a question (/tech/inbox/:id).
 * The expert sees the question, the technician's note and what Kaarigar said, then either
 *  - records a voice answer: it becomes a Phase 2 note (check screen -> supervisor -> knowledge), or
 *  - sends a quick text message ("Check fuse F3, coming in 10 minutes").
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { errorCode } from '../capture/captureApi';
import { useRecorder } from '../capture/useRecorder';
import VoiceGauge, { fmt } from '../capture/VoiceGauge';
import { BigButton, Card, MachineChip, Screen, Spinner, TopBar } from '../capture/ui';
import { expertEscalation, replyText, replyVoice, takeEscalation, type Source } from './assistApi';
import { parseAnswerText } from './parseAnswer';
import { ago, AnswerView, AudioMini, Notice } from './parts';
import SourceSheet from './SourceSheet';

const MAX_SEC = 180;
const MIN_SEC = 3;

export default function EscalationAnswerScreen() {
  const { id = '' } = useParams();
  const nav = useNavigate();
  const qc = useQueryClient();
  const { t, i18n } = useTranslation();
  const [mode, setMode] = useState<'choose' | 'voice' | 'text'>('choose');
  const [text, setText] = useState('');
  const [openSource, setOpenSource] = useState<Source | null>(null);
  const rec = useRecorder(MAX_SEC);
  const q = useQuery({ queryKey: ['expert', 'escalation', id], queryFn: () => expertEscalation(id) });
  const e = q.data;

  const audioUrl = useMemo(() => (rec.blob ? URL.createObjectURL(rec.blob) : null), [rec.blob]);
  useEffect(() => () => { if (audioUrl) URL.revokeObjectURL(audioUrl); }, [audioUrl]);

  const refresh = () => qc.invalidateQueries({ queryKey: ['expert'] });
  const take = useMutation({ mutationFn: () => takeEscalation(id), onSuccess: refresh });
  const voice = useMutation({
    mutationFn: () => replyVoice(id, rec.blob as Blob, rec.mimeType),
    onSuccess: ({ record_id }) => { refresh(); nav(`/tech/records/${record_id}`, { replace: true }); },
  });
  const quick = useMutation({ mutationFn: () => replyText(id, text.trim()), onSuccess: () => { refresh(); setMode('choose'); } });

  // The expert reads English best for the AI's attempt; fall back to the technician's language.
  const attempt = e?.kaarigar.answer_en ?? e?.kaarigar.answer_local ?? '';
  const parts = useMemo(() => parseAnswerText(attempt === 'NO_ANSWER' ? '' : attempt), [attempt]);
  const tooShort = rec.state === 'stopped' && rec.seconds < MIN_SEC;
  const err = voice.error ?? quick.error ?? take.error;

  return (
    <Screen>
      <TopBar onBack={() => nav('/tech/inbox')} title={t('assist.answerQ.title')}
        right={e?.machine ? <MachineChip code={e.machine.code} /> : undefined} />
      {q.isLoading && <Spinner size={22} />}
      {q.isError && <Notice tone="alert">{t('assist.question.notFound')}</Notice>}
      {e && (
        <div className="flex flex-col gap-4">
          <Card>
            <div className="text-xs text-[var(--ink-muted)]">{e.asked_by?.name} · {ago(e.created_at, i18n.language)}</div>
            <p className="mt-1 text-[17px] font-semibold leading-snug">{e.question.original}</p>
            {e.question.en && e.question.en !== e.question.original && (
              <p className="mt-1 text-sm text-[var(--ink-muted)]">{e.question.en}</p>
            )}
            {e.note && <p className="mt-3 rounded-xl bg-[var(--white)] px-3 py-2 text-sm"><b>{t('assist.answerQ.note')}</b> {e.note}</p>}
          </Card>

          <section>
            <h2 className="mb-2 text-sm font-semibold text-[var(--ink-muted)]">
              {e.kaarigar.status === 'answered' ? t('assist.answerQ.kaarigarSaid') : t('assist.answerQ.kaarigarCouldNot')}
            </h2>
            {e.kaarigar.status === 'answered' && parts.steps.length > 0 && (
              <AnswerView parts={parts} sources={e.kaarigar.sources} onOpenSource={setOpenSource} />
            )}
            {e.feedback === 'not_fixed' && <p className="mt-2 text-sm text-[var(--alert)]">{t('assist.answerQ.didNotWork')}</p>}
          </section>

          {e.status === 'answered' && (
            <Notice tone="ok">
              {t('assist.answerQ.answeredBy', { name: e.replied_by?.name ?? '' })}
              {e.reply.text && <span className="mt-1 block text-[var(--ink)]">{e.reply.text}</span>}
            </Notice>
          )}
          {e.status === 'closed' && <Notice>{t(`assist.reply.closed.${e.close_reason ?? 'not_needed'}`)}</Notice>}
          {e.reply.record?.audio_url && <AudioMini src={e.reply.record.audio_url} label={t('assist.answerQ.yourVoice')} />}

          {e.status === 'open' && e.reply_in_progress && e.reply.record && (
            <Link to={`/tech/records/${e.reply.record.id}`}
              className="flex min-h-[60px] items-center justify-center rounded-[var(--radius-button,18px)] bg-[var(--green)] px-5 font-semibold text-[var(--white)]">
              {t('assist.answerQ.continueDraft')}
            </Link>
          )}

          {e.status === 'open' && !e.reply_in_progress && (
            <div className="space-y-3">
              {!e.assigned_to && (
                <BigButton kind="secondary" onClick={() => take.mutate()} disabled={take.isPending}>{t('assist.answerQ.take')}</BigButton>
              )}

              {mode === 'choose' && (
                <>
                  {e.machine && <BigButton onClick={() => setMode('voice')}>{t('assist.answerQ.recordAnswer')}</BigButton>}
                  <BigButton kind="secondary" onClick={() => setMode('text')}>{t('assist.answerQ.quickText')}</BigButton>
                  <p className="text-center text-xs text-[var(--ink-muted)]">{t('assist.answerQ.voiceHelps')}</p>
                </>
              )}

              {mode === 'voice' && rec.state !== 'stopped' && (
                <>
                  <VoiceGauge recording={rec.state === 'recording'} level={rec.level} seconds={rec.seconds} maxSec={MAX_SEC}
                    disabled={rec.state === 'requesting'} label={rec.state === 'recording' ? t('capture.record.stop') : t('capture.record.start')}
                    onPress={() => (rec.state === 'recording' ? rec.stop() : rec.start())} />
                  <p className="text-center text-sm text-[var(--ink-muted)]">{t('assist.answerQ.sayFix')}</p>
                  {rec.state === 'error' && rec.error && <Notice tone="alert">{t(`capture.record.errors.${rec.error}`)}</Notice>}
                  <BigButton kind="quiet" onClick={() => { rec.reset(); setMode('choose'); }}>{t('capture.cancel')}</BigButton>
                </>
              )}

              {mode === 'voice' && rec.state === 'stopped' && audioUrl && (
                <>
                  <Card>
                    <div className="mb-2 flex justify-between text-sm"><b>{t('capture.record.listenBack')}</b><span>{fmt(rec.seconds)}</span></div>
                    <AudioMini src={audioUrl} label={fmt(rec.seconds)} />
                  </Card>
                  {tooShort && <Notice tone="alert">{t('capture.errors.too_short')}</Notice>}
                  <BigButton onClick={() => voice.mutate()} disabled={tooShort || voice.isPending}>
                    {voice.isPending ? <span className="inline-flex items-center gap-2"><Spinner />{t('capture.record.sending')}</span> : t('assist.answerQ.sendVoice')}
                  </BigButton>
                  <BigButton kind="secondary" onClick={() => rec.reset()} disabled={voice.isPending}>{t('capture.record.again')}</BigButton>
                </>
              )}

              {mode === 'text' && (
                <form onSubmit={(ev) => { ev.preventDefault(); if (text.trim().length >= 2) quick.mutate(); }} className="space-y-3">
                  <label htmlFor="reply-text" className="block text-sm font-semibold">{t('assist.answerQ.textLabel')}</label>
                  <textarea id="reply-text" rows={3} value={text} onChange={(ev) => setText(ev.target.value.slice(0, 1000))} autoFocus
                    className="w-full rounded-2xl border border-[var(--line)] bg-[var(--white)] p-3 text-base focus:outline-none focus:ring-2 focus:ring-[var(--green)]" />
                  <BigButton type="submit" disabled={text.trim().length < 2 || quick.isPending}>{t('assist.answerQ.sendText')}</BigButton>
                  <BigButton kind="quiet" onClick={() => setMode('choose')}>{t('capture.cancel')}</BigButton>
                </form>
              )}

              {err && <Notice tone="alert">{t(`assist.errors.${errorCode(err)}`, { defaultValue: t('assist.errors.network') })}</Notice>}
            </div>
          )}
        </div>
      )}
      <SourceSheet source={openSource} onClose={() => setOpenSource(null)} />
    </Screen>
  );
}
