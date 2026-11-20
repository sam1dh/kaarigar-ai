/**
 * 04 My question (/tech/questions/:id): the saved answer, feedback, and what happened with the expert.
 * Updates live when the expert replies (Supabase Realtime on `escalations`).
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate, useParams } from 'react-router-dom';
import { Card, MachineChip, Screen, Spinner, TopBar } from '../capture/ui';
import AfterAnswer from './AfterAnswer';
import { getQuery, sendFeedback, type QueryView, type Source } from './assistApi';
import { ago, AnswerView, AudioMini, Notice, SourceList } from './parts';
import ReadAloud from './ReadAloud';
import { useLiveRefresh } from './realtime';
import SourceSheet from './SourceSheet';

function ExpertReply({ q }: { q: QueryView }) {
  const { t, i18n } = useTranslation();
  const qc = useQueryClient();
  const fixed = useMutation({
    mutationFn: () => sendFeedback(q.id, 'fixed'),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['assist'] }),
  });
  const e = q.escalation;
  if (!e) return null;
  if (e.status === 'open') {
    return (
      <div className="space-y-2">
        <Notice>
          {e.assigned_to?.name ? t('assist.reply.waitingFor', { name: e.assigned_to.name }) : t('assist.reply.waiting')}
          {e.reply_in_progress && <> · {t('assist.reply.recording')}</>}
        </Notice>
        {q.can.feedback && (
          <button type="button" onClick={() => fixed.mutate()} disabled={fixed.isPending}
            className="text-sm font-semibold text-[var(--green-deep)] underline underline-offset-4 disabled:opacity-50">
            {t('assist.reply.fixedMyself')}
          </button>
        )}
      </div>
    );
  }
  if (e.status === 'closed' && !e.reply?.text && !e.reply?.record) {
    return <Notice>{t(`assist.reply.closed.${e.close_reason ?? 'not_needed'}`)}</Notice>;
  }
  const local = e.reply?.local;
  const rec = e.reply?.record;
  const f = local?.fields ?? rec?.fields;
  const steps = (f?.steps ?? []).filter(Boolean);
  return (
    <Card className="space-y-3 border-2 border-[var(--green)] bg-[var(--white)]">
      <div className="flex items-baseline justify-between gap-2">
        <b style={{ fontFamily: 'var(--font-heading)' }}>{t('assist.reply.from', { name: e.replied_by?.name ?? '' })}</b>
        <span className="text-xs text-[var(--ink-faint)]">{ago(e.answered_at, i18n.language)}</span>
      </div>
      {e.reply?.text && <p className="text-[17px] leading-relaxed">{local?.text ?? e.reply.text}</p>}
      {rec?.audio_url && <AudioMini src={rec.audio_url} label={t('assist.source.expertVoice')} />}
      {f?.safety_note && <Notice><b className="mr-1 text-[var(--ink)]">{t('assist.answer.safety')}</b><span className="text-[var(--ink)]">{f.safety_note}</span></Notice>}
      {f?.fix && <p className="font-semibold leading-snug">{f.fix}</p>}
      {steps.length > 0 && <ol className="list-decimal space-y-1 pl-5 leading-relaxed">{steps.map((s, i) => <li key={i}>{s}</li>)}</ol>}
      {rec && rec.status !== 'approved' && <p className="text-xs text-[var(--ink-muted)]">{t('assist.reply.notReviewedYet')}</p>}
      {rec?.status === 'approved' && <p className="text-xs text-[var(--green-deep)]">{t('assist.reply.addedToKnowledge')}</p>}
    </Card>
  );
}

export default function QuestionScreen() {
  const { id = '' } = useParams();
  const nav = useNavigate();
  const { t, i18n } = useTranslation();
  const [openSource, setOpenSource] = useState<Source | null>(null);
  const q = useQuery({ queryKey: ['assist', 'query', id], queryFn: () => getQuery(id), refetchInterval: 60_000 });
  useLiveRefresh('escalations', [['assist', 'query', id], ['assist', 'queries']], !!q.data?.escalation);
  const v = q.data;

  return (
    <Screen>
      <TopBar onBack={() => nav('/tech/questions')} title={t('assist.question.title')}
        right={v?.machine ? <MachineChip code={v.machine.code} /> : undefined} />
      {q.isLoading && <div className="py-8 text-[var(--ink-muted)]"><Spinner size={24} /></div>}
      {q.isError && <Notice tone="alert">{t('assist.question.notFound')}</Notice>}
      {v && (
        <div className="flex flex-col gap-4">
          <div className="self-end max-w-[85%] rounded-[22px] rounded-br-md bg-[var(--green)] px-4 py-3 text-[var(--white)]">
            <div className="text-xs opacity-80">{t('assist.ask.youAsked')} · {ago(v.created_at, i18n.language)}</div>
            <div className="text-[17px] leading-snug">{v.question.original ?? v.question.en}</div>
          </div>

          {v.status === 'answered' && v.answer.parts && (
            <AnswerView parts={v.answer.parts} sources={v.sources} onOpenSource={setOpenSource} />
          )}
          {v.status === 'no_answer' && <Notice>{t('assist.answer.noAnswer')}</Notice>}
          {v.status === 'failed' && <Notice tone="alert">{t(`assist.errors.${v.error?.code ?? 'internal'}`, { defaultValue: t('assist.errors.internal') })}</Notice>}
          {v.status === 'answering' && <Notice>{t('assist.question.stillAnswering')}</Notice>}

          {v.can.read_aloud && v.answer.parts && <ReadAloud queryId={v.id} parts={v.answer.parts} lang={v.language ?? i18n.language} />}

          <ExpertReply q={v} />

          {!v.escalation && (v.can.feedback || v.can.escalate) && (
            <AfterAnswer key={`${v.id}-${v.feedback}`} queryId={v.id} status={v.status}
              suggestEscalate={v.suggest_escalate} feedback={v.feedback} />
          )}

          {v.status === 'answered' && v.answer.parts && (
            <SourceList sources={v.sources} used={v.answer.parts.refs_used} onOpen={setOpenSource} />
          )}
        </div>
      )}
      <SourceSheet source={openSource} onClose={() => setOpenSource(null)} />
    </Screen>
  );
}
