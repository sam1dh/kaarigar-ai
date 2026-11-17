/**
 * /tech/records/:id — one screen that follows the note through its life:
 *   processing  -> progress steps (polls every 2 s)
 *   failed      -> friendly error, Try again / Record again
 *   07 Check your note (expert_review) -> edit in own language, send
 *   pending / approved / rejected -> read-only status (rejected shows the supervisor's reason)
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate, useParams } from 'react-router-dom';
import {
  discardRecord, errorCode, getRecord, retryRecord, submitRecord,
  type CaptureRecord, type FieldEdits,
} from './captureApi';
import AudioPlayer from './AudioPlayer';
import FieldEditor, { type DisplayFields } from './FieldEditor';
import { BigButton, Card, CheckIcon, IssueList, MachineChip, Screen, Spinner, StatusPill, TopBar } from './ui';

const STEPS = ['transcribing', 'extracting', 'checking', 'translating'] as const;

function englishDisplay(r: CaptureRecord): DisplayFields {
  const f = r.fields;
  return { symptom: f.symptom, cause: f.cause, fix: f.fix, steps: f.steps ?? [], safety_note: f.safety_note,
    parts: f.parts, tools: f.tools, downtime_min: f.downtime_min };
}

function localDisplay(r: CaptureRecord): DisplayFields | null {
  const l = r.fields_local;
  if (!l) return null;
  return { symptom: l.symptom, cause: l.cause, fix: l.fix, steps: l.steps ?? [], safety_note: l.safety_note,
    parts: r.fields.parts, tools: r.fields.tools, downtime_min: r.fields.downtime_min };
}

export default function NoteScreen() {
  const { id = '' } = useParams();
  const nav = useNavigate();
  const qc = useQueryClient();
  const { t } = useTranslation();
  const q = useQuery({
    queryKey: ['capture', 'record', id],
    queryFn: () => getRecord(id),
    refetchInterval: (query) => (query.state.data?.processing ? 2000 : false),
  });
  const r = q.data;

  const [showEnglish, setShowEnglish] = useState(false);
  const [edits, setEdits] = useState<FieldEdits>({});
  const [actionError, setActionError] = useState<string | null>(null);
  const [confirmDiscard, setConfirmDiscard] = useState(false);

  const local = useMemo(() => (r ? localDisplay(r) : null), [r]);
  const english = useMemo(() => (r ? englishDisplay(r) : null), [r]);
  const usingLocal = !!local && !showEnglish;
  const display = usingLocal ? local : english;
  const dirty = Object.keys(edits).length > 0;

  const retry = useMutation({
    mutationFn: () => retryRecord(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['capture', 'record', id] }),
    onError: (e) => setActionError(errorCode(e)),
  });
  const submit = useMutation({
    mutationFn: () => submitRecord(id, edits, usingLocal && r ? r.language : 'en-IN'),
    onSuccess: (rec) => {
      qc.setQueryData(['capture', 'record', id], rec);
      qc.invalidateQueries({ queryKey: ['capture', 'mine'] });
      nav(`/tech/records/${id}/sent`, { replace: true });
    },
    onError: (e) => setActionError(errorCode(e)),
  });
  const discard = useMutation({
    mutationFn: () => discardRecord(id),
    onError: (e) => setActionError(errorCode(e)),
  });
  const recordAgain = async () => {
    if (!r) return;
    if (r.can.discard) await discard.mutateAsync().catch(() => undefined);
    qc.invalidateQueries({ queryKey: ['capture', 'mine'] });
    nav(`/tech/machines/${encodeURIComponent(r.machine.code)}/record`, { replace: true });
  };

  if (q.isLoading) {
    return <Screen><div className="m-auto text-[var(--ink-muted)]"><Spinner size={28} /></div></Screen>;
  }
  if (q.isError || !r) {
    return (
      <Screen>
        <TopBar onBack={() => nav('/tech')} title={t('capture.note.title')} />
        <p role="alert" className="rounded-2xl bg-[var(--alert-tint)] px-4 py-3 text-[var(--alert)]">{t('capture.note.notFound')}</p>
      </Screen>
    );
  }

  const back = () => nav(`/tech/machines/${encodeURIComponent(r.machine.code)}`);
  const header = <TopBar onBack={back} title={t('capture.note.title')} right={<MachineChip code={r.machine.code} />} />;

  // ------------------------------------------------------------ processing
  if (r.processing) {
    const current = r.stage === 'queued' ? 'transcribing' : r.stage;
    const idx = STEPS.indexOf(current as (typeof STEPS)[number]);
    const steps = STEPS.filter((s) => s !== 'translating' || !r.language.startsWith('en'));
    return (
      <Screen>
        {header}
        <Card className="mt-4">
          <p className="mb-4 font-semibold">{t('capture.note.working')}</p>
          <ol className="space-y-4" aria-live="polite">
            {steps.map((s) => {
              const i = STEPS.indexOf(s);
              const state = i < idx ? 'done' : i === idx ? 'now' : 'todo';
              return (
                <li key={s} className={`flex items-center gap-3 ${state === 'todo' ? 'text-[var(--ink-faint)]' : ''}`}>
                  <span className={`grid h-8 w-8 place-items-center rounded-full ${state === 'done' ? 'bg-[var(--green)] text-white' : state === 'now' ? 'bg-[var(--green-tint)] text-[var(--green-deep)]' : 'bg-[var(--line)]'}`}>
                    {state === 'done' ? <CheckIcon /> : state === 'now' ? <Spinner /> : null}
                  </span>
                  {t(`capture.note.steps.${s}`)}
                </li>
              );
            })}
          </ol>
          <p className="mt-5 text-sm text-[var(--ink-muted)]">{t('capture.note.canLeave')}</p>
        </Card>
      </Screen>
    );
  }

  // ------------------------------------------------------------ failed
  if (r.stage === 'failed' && r.error) {
    return (
      <Screen>
        {header}
        <Card className="mt-4">
          <p role="alert" className="text-lg font-semibold">{t(`capture.errors.${r.error.code}`, { defaultValue: t('capture.errors.internal') })}</p>
        </Card>
        {actionError && <p role="alert" className="mt-3 text-sm text-[var(--alert)]">{t(`capture.errors.${actionError}`, { defaultValue: t('capture.errors.internal') })}</p>}
        <div className="mt-auto space-y-3 pt-6">
          {r.can.retry && (
            <BigButton onClick={() => retry.mutate()} disabled={retry.isPending}>{t('capture.note.tryAgain')}</BigButton>
          )}
          <BigButton kind={r.can.retry ? 'secondary' : 'primary'} onClick={recordAgain} disabled={discard.isPending}>
            {t('capture.record.again')}
          </BigButton>
        </div>
      </Screen>
    );
  }

  // ------------------------------------------------------------ 07 check your note
  if (r.can.submit && display) {
    const ai = r.ai_check;
    const messages = usingLocal ? r.fields_local?.issues : undefined;
    const summary = usingLocal ? r.fields_local?.summary : ai?.summary;
    return (
      <Screen>
        {header}
        <p className="mb-3 text-sm text-[var(--ink-muted)]">{t('capture.check.intro')}</p>
        {summary && <Card className="mb-3"><p className="font-semibold">{summary}</p></Card>}
        {ai && <div className="mb-4"><IssueList issues={ai.issues} safetyOk={ai.safety_ok} messages={messages} /></div>}

        {local && (
          <div className="mb-3 flex justify-end">
            <button type="button" disabled={dirty} onClick={() => setShowEnglish((v) => !v)}
              className="text-sm font-semibold text-[var(--green)] disabled:text-[var(--ink-faint)]"
              title={dirty ? t('capture.check.toggleLocked') : undefined}>
              {showEnglish ? t('capture.check.showMine') : t('capture.check.showEnglish')}
            </button>
          </div>
        )}

        <FieldEditor display={display} missing={r.fields.missing} editable onChange={setEdits} />

        <details className="mb-3 rounded-2xl bg-[var(--surface)] p-3">
          <summary className="cursor-pointer text-sm font-semibold">{t('capture.check.whatYouSaid')}</summary>
          {r.audio_url && (
            <div className="mt-3">
              <AudioPlayer src={r.audio_url} knownSeconds={r.audio_seconds} label={t('capture.check.whatYouSaid')} />
            </div>
          )}
          {r.transcript_en && <p className="mt-3 text-sm text-[var(--ink-muted)]">{r.transcript_en}</p>}
        </details>

        {actionError && (
          <p role="alert" className="mb-3 rounded-2xl bg-[var(--alert-tint)] px-4 py-3 text-sm text-[var(--alert)]">
            {t(`capture.errors.${actionError}`, { defaultValue: t('capture.errors.internal') })}
          </p>
        )}

        <div className="mt-auto space-y-3 pt-4">
          <BigButton onClick={() => { setActionError(null); submit.mutate(); }} disabled={submit.isPending || discard.isPending}>
            {submit.isPending ? <span className="inline-flex items-center gap-2"><Spinner /> {t('capture.check.sending')}</span>
              : t('capture.check.send')}
          </BigButton>
          <BigButton kind="secondary" onClick={recordAgain} disabled={submit.isPending || discard.isPending}>
            {t('capture.record.again')}
          </BigButton>
          {!confirmDiscard ? (
            <BigButton kind="quiet" onClick={() => setConfirmDiscard(true)}>{t('capture.check.discard')}</BigButton>
          ) : (
            <Card className="border border-[var(--alert)]">
              <p className="mb-3 text-sm">{t('capture.check.discardConfirm')}</p>
              <div className="flex gap-2">
                <BigButton kind="secondary" onClick={() => setConfirmDiscard(false)}>{t('capture.cancel')}</BigButton>
                <BigButton kind="danger" onClick={async () => { await discard.mutateAsync(); back(); }}>
                  {t('capture.check.discardYes')}
                </BigButton>
              </div>
            </Card>
          )}
        </div>
      </Screen>
    );
  }

  // ------------------------------------------------------------ status (pending / approved / rejected)
  return (
    <Screen>
      {header}
      <Card className="mb-4">
        <div className="mb-2 flex items-center justify-between gap-2">
          <span className="font-semibold">{t(`capture.note.statusTitle.${r.status}`)}</span>
          <StatusPill rec={r} />
        </div>
        {r.status === 'rejected' && r.reject_reason && (
          <p className="rounded-xl bg-[var(--alert-tint)] px-3 py-2 text-sm">
            <b>{r.reviewer?.name ?? t('capture.note.supervisor')}:</b> {r.reject_reason}
          </p>
        )}
        {r.status === 'pending' && <p className="text-sm text-[var(--ink-muted)]">{t('capture.sent.next')}</p>}
        {r.status === 'approved' && <p className="text-sm text-[var(--ink-muted)]">{t('capture.note.approvedText')}</p>}
      </Card>
      {display && <FieldEditor display={display} missing={r.fields.missing} editable={false} onChange={() => undefined} />}
      {r.status === 'rejected' && (
        <div className="mt-auto pt-4"><BigButton onClick={() => nav(`/tech/machines/${encodeURIComponent(r.machine.code)}/record`)}>{t('capture.record.again')}</BigButton></div>
      )}
    </Screen>
  );
}
