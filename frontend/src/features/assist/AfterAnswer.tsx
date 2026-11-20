/**
 * Under every finished answer: "Did this fix it?" and "Ask an expert".
 * - Answered: Fixed / Still not working. "Still not working" leads straight to Ask an expert.
 * - No answer or failed: Ask an expert is the main action.
 * - Low confidence: a quieter "Not sure? Ask an expert".
 */
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { errorCode } from '../capture/captureApi';
import { BigButton, Spinner } from '../capture/ui';
import { escalateQuery, sendFeedback, type Outcome, type Person, type QueryStatus } from './assistApi';
import { Notice, Sheet } from './parts';

interface Props {
  queryId: string;
  status: QueryStatus;
  suggestEscalate: boolean;
  feedback?: Outcome | null;
  escalated?: { assigned_to: Person | null } | null;
}

export default function AfterAnswer({ queryId, status, suggestEscalate, feedback: initialFeedback = null, escalated = null }: Props) {
  const { t } = useTranslation();
  const nav = useNavigate();
  const qc = useQueryClient();
  const [feedback, setFeedback] = useState<Outcome | null>(initialFeedback);
  const [sheet, setSheet] = useState(false);
  const [note, setNote] = useState('');
  const [sent, setSent] = useState<{ assigned_to: Person | null } | null>(escalated);

  const fb = useMutation({
    mutationFn: (o: Outcome) => sendFeedback(queryId, o),
    onMutate: (o) => {
      // "Still not working" opens Ask an expert straight away, even on a slow network
      if (o === 'not_fixed' && !sent) setSheet(true);
    },
    onSuccess: (_d, o) => {
      setFeedback(o);
      qc.invalidateQueries({ queryKey: ['assist'] });
    },
  });

  const esc = useMutation({
    mutationFn: () => escalateQuery(queryId, note.trim() || undefined),
    onSuccess: (res) => {
      setSent({ assigned_to: res.assigned_to });
      setSheet(false);
      qc.invalidateQueries({ queryKey: ['assist'] });
    },
    onError: (e) => {
      if (errorCode(e) === 'already_escalated') {
        setSent({ assigned_to: null });
        setSheet(false);
      }
    },
  });

  const answered = status === 'answered';

  return (
    <div className="space-y-3">
      {answered && !sent && (
        <div className="rounded-[var(--radius-card,22px)] bg-[var(--surface)] p-4">
          <p className="mb-3 font-semibold">{feedback === 'fixed' ? t('assist.feedback.thanks') : t('assist.feedback.question')}</p>
          {feedback !== 'fixed' && (
            <div className="grid grid-cols-2 gap-3">
              <BigButton onClick={() => fb.mutate('fixed')} disabled={fb.isPending}>{t('assist.feedback.fixed')}</BigButton>
              <BigButton kind="secondary" onClick={() => fb.mutate('not_fixed')} disabled={fb.isPending}
                aria-pressed={feedback === 'not_fixed'}>{t('assist.feedback.notFixed')}</BigButton>
            </div>
          )}
          {fb.isError && <p role="alert" className="mt-2 text-sm text-[var(--alert)]">{t('assist.errors.network')}</p>}
        </div>
      )}

      {sent ? (
        <Notice tone="ok">
          {sent.assigned_to?.name ? t('assist.escalate.sentTo', { name: sent.assigned_to.name }) : t('assist.escalate.sent')}{' '}
          <button type="button" className="font-semibold underline underline-offset-4" onClick={() => nav(`/tech/questions/${queryId}`)}>
            {t('assist.escalate.track')}
          </button>
        </Notice>
      ) : !answered || feedback === 'not_fixed' ? (
        <BigButton onClick={() => setSheet(true)}>{t('assist.escalate.button')}</BigButton>
      ) : suggestEscalate && feedback !== 'fixed' ? (
        <BigButton kind="quiet" onClick={() => setSheet(true)}>{t('assist.escalate.notSure')}</BigButton>
      ) : null}

      <Sheet open={sheet} onClose={() => setSheet(false)} title={t('assist.escalate.title')}>
        <p className="mb-3 text-sm text-[var(--ink-muted)]">{t('assist.escalate.help')}</p>
        <label className="mb-1 block text-sm font-semibold" htmlFor="esc-note">{t('assist.escalate.noteLabel')}</label>
        <textarea id="esc-note" value={note} onChange={(e) => setNote(e.target.value.slice(0, 500))} rows={3}
          placeholder={t('assist.escalate.notePlaceholder')}
          className="mb-4 w-full rounded-2xl border border-[var(--line)] bg-[var(--white)] p-3 text-base focus:outline-none focus:ring-2 focus:ring-[var(--green)]" />
        {esc.isError && errorCode(esc.error) !== 'already_escalated' && (
          <p role="alert" className="mb-3 text-sm text-[var(--alert)]">{t('assist.errors.network')}</p>
        )}
        <BigButton onClick={() => esc.mutate()} disabled={esc.isPending}>
          {esc.isPending ? <span className="inline-flex items-center gap-2"><Spinner />{t('assist.escalate.sending')}</span> : t('assist.escalate.send')}
        </BigButton>
      </Sheet>
    </div>
  );
}
