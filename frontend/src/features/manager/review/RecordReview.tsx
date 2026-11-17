/** Detail panel of the review queue: listen, read, edit (English), approve or reject with a reason. */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  approveRecord, errorCode, getReviewRecord, rejectRecord, type FieldEdits, type Issue,
} from '../../capture/captureApi';
import AudioPlayer from '../../capture/AudioPlayer';
import FieldEditor, { type DisplayFields } from '../../capture/FieldEditor';
import { IssueList, Spinner } from '../../capture/ui';

type ReasonKey = 'cause' | 'problem' | 'steps' | 'safety' | 'wrongMachine';

const SEVERITY: Record<Issue['severity'], number> = { high: 0, medium: 1, low: 2 };
const bySeverity = (a: Issue, b: Issue) => SEVERITY[a.severity] - SEVERITY[b.severity];

/** Maps the AI's `missing` field names to the reason chips. */
const MISSING_TO_REASON: Record<string, ReasonKey> = {
  cause: 'cause',
  symptom: 'problem',
  steps: 'steps',
  safety_note: 'safety',
};

export default function RecordReview({ id, onDone }: { id: string; onDone: () => void }) {
  const { t, i18n } = useTranslation();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ['review', 'record', id], queryFn: () => getReviewRecord(id) });
  const r = q.data;
  const [edits, setEdits] = useState<FieldEdits>({});
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState('');
  const [chosen, setChosen] = useState<Set<ReasonKey>>(new Set());
  const [showExpertVersion, setShowExpertVersion] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const display = useMemo<DisplayFields | null>(() => r ? ({
    symptom: r.fields.symptom, cause: r.fields.cause, fix: r.fields.fix, steps: r.fields.steps ?? [],
    safety_note: r.fields.safety_note, parts: r.fields.parts, tools: r.fields.tools, downtime_min: r.fields.downtime_min,
  }) : null, [r]);

  const localDisplay = useMemo<DisplayFields | null>(() => r?.fields_local ? ({
    symptom: r.fields_local.symptom, cause: r.fields_local.cause, fix: r.fields_local.fix,
    steps: r.fields_local.steps ?? [], safety_note: r.fields_local.safety_note,
    parts: r.fields.parts, tools: r.fields.tools, downtime_min: r.fields.downtime_min,
  }) : null, [r]);

  const after = () => {
    qc.invalidateQueries({ queryKey: ['review'] });
    onDone();
  };
  const approve = useMutation({ mutationFn: () => approveRecord(id, edits), onSuccess: after, onError: (e) => setErr(errorCode(e)) });
  const reject = useMutation({ mutationFn: () => rejectRecord(id, reason.trim()), onSuccess: after, onError: (e) => setErr(errorCode(e)) });

  if (q.isLoading || !r || !display) return <div className="p-6 text-[var(--ink-muted)]"><Spinner size={24} /></div>;

  const busy = approve.isPending || reject.isPending;
  const merged = { ...r.fields, ...edits };
  const canApprove = !!merged.symptom && !!merged.fix && r.can.review;

  const chipKeys: ReasonKey[] = ['cause', 'problem', 'steps', 'safety', 'wrongMachine'];
  const chipText = (k: ReasonKey) => t(`review.reasons.${k}`);

  const openReject = () => {
    const keys = Array.from(new Set(
      (r.fields.missing ?? []).map((m) => MISSING_TO_REASON[m]).filter((k): k is ReasonKey => !!k),
    ));
    setChosen(new Set(keys));
    setReason(keys.map(chipText).join(' '));
    setRejecting(true);
  };

  const toggleChip = (k: ReasonKey) => {
    const text = chipText(k);
    const on = chosen.has(k);
    const next = new Set(chosen);
    if (on) next.delete(k); else next.add(k);
    setChosen(next);
    setReason((prev) => (
      on
        ? prev.split(text).join('').replace(/\s{2,}/g, ' ').trim()
        : `${prev.trim() ? `${prev.trim()} ` : ''}${text}`
    ));
  };

  return (
    <article className="flex h-full flex-col rounded-[var(--radius-card,22px)] bg-[var(--white)]">
      <header className="flex flex-wrap items-baseline gap-x-4 gap-y-1 border-b border-[var(--line)] px-6 py-4">
        <h2 className="text-2xl font-bold text-[var(--green-deep)]" style={{ fontFamily: 'var(--font-heading)' }}>{r.machine.code}</h2>
        <span className="text-[var(--ink-muted)]">{r.machine.name}{r.machine.line ? ` · ${r.machine.line}` : ''}</span>
        <span className="ml-auto text-sm text-[var(--ink-muted)]">
          {r.author.name} · {r.submitted_at && new Date(r.submitted_at).toLocaleString(i18n.language, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })}
          {r.audio_seconds ? ` · ${Math.round(r.audio_seconds)} s` : ''}
        </span>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto p-6">
        {r.ai_check?.summary && (
          <p className="mb-4 rounded-2xl bg-[var(--green-tint)] px-4 py-3 font-semibold text-[var(--green-deep)]">
            {r.ai_check.summary}
          </p>
        )}
        <div className="grid gap-6 xl:grid-cols-[minmax(320px,0.9fr)_1.1fr]">
          {/* LEFT: what the expert said */}
          <section className="space-y-4">
            {r.audio_url && <AudioPlayer src={r.audio_url} knownSeconds={r.audio_seconds} label={r.author.name ?? ''} />}
            <div className="rounded-2xl bg-[var(--surface)] p-4">
              <h3 className="mb-2 text-sm font-semibold text-[var(--ink-muted)]">{t('review.transcriptEn')}</h3>
              <p className="whitespace-pre-wrap text-[15px] leading-relaxed">{r.transcript_en ?? '—'}</p>
            </div>
            {r.ai_check && (
              <div>
                <h3 className="mb-2 text-sm font-semibold text-[var(--ink-muted)]">
                  {t('review.aiCheck')} · {t('review.inEnglish')}
                </h3>
                <IssueList issues={[...r.ai_check.issues].sort(bySeverity)} safetyOk={r.ai_check.safety_ok} />
              </div>
            )}
          </section>

          {/* RIGHT: the record that will be saved */}
          <section>
            <div className="mb-2 flex items-center justify-between gap-2">
              <h3 className="text-sm font-semibold text-[var(--ink-muted)]">
                {t('review.record')} · {t('review.savedInEnglish')}
              </h3>
              {localDisplay && (
                <button type="button" className="shrink-0 text-sm font-semibold text-[var(--green)]"
                  onClick={() => setShowExpertVersion((v) => !v)}>
                  {showExpertVersion ? t('review.showEnglishRecord') : t('review.showExpertVersion')}
                </button>
              )}
            </div>
            {showExpertVersion && localDisplay
              ? <FieldEditor display={localDisplay} missing={r.fields.missing} editable={false} onChange={() => undefined} compact />
              : <FieldEditor display={display} missing={r.fields.missing} editable={r.can.review} onChange={setEdits} compact
                  emptyPlaceholder={t('review.emptyFieldHint')} />}
          </section>
        </div>

        {err && (
          <p role="alert" className="mt-4 rounded-xl bg-[var(--alert-tint)] px-3 py-2 text-sm text-[var(--alert)]">
            {t(`review.errors.${err}`, { defaultValue: t('capture.errors.internal') })}
          </p>
        )}
      </div>

      <footer className="sticky bottom-0 border-t border-[var(--line)] bg-[var(--white)] px-6 py-4">
        {r.can.review ? (
          !rejecting ? (
            <>
              <div className="flex gap-3">
                <button type="button" disabled={!canApprove || busy} onClick={() => { setErr(null); approve.mutate(); }}
                  className="h-12 flex-1 rounded-[var(--radius-button,18px)] bg-[var(--green)] font-semibold text-white disabled:opacity-50">
                  {approve.isPending ? <Spinner /> : Object.keys(edits).length ? t('review.approveEdited') : t('review.approve')}
                </button>
                <button type="button" disabled={busy} onClick={openReject}
                  className="h-12 rounded-[var(--radius-button,18px)] border border-[var(--line)] px-6 font-semibold">
                  {t('review.reject')}
                </button>
              </div>
              {!canApprove && (
                <p className="mt-2 text-sm text-[var(--alert)]">{t('review.needProblemAndFix')}</p>
              )}
            </>
          ) : (
            <div className="rounded-2xl border border-[var(--alert)] p-4">
              <div className="mb-3 flex flex-wrap gap-2">
                {chipKeys.map((k) => {
                  const on = chosen.has(k);
                  return (
                    <button key={k} type="button" aria-pressed={on} onClick={() => toggleChip(k)}
                      className={`rounded-full border px-3 py-1.5 text-sm hover:border-[var(--alert)] ${on ? 'border-[var(--alert)] bg-[var(--alert-tint)] text-[var(--alert)]' : 'border-[var(--line)]'}`}>
                      {chipText(k)}
                    </button>
                  );
                })}
              </div>
              <label htmlFor="reject-reason" className="mb-2 block text-sm font-semibold">{t('review.reasonLabel')}</label>
              <textarea id="reject-reason" rows={3} value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500}
                placeholder={t('review.reasonPlaceholder')}
                className="mb-3 w-full rounded-xl border border-[var(--line)] px-3 py-2 focus:border-[var(--alert)] focus:outline-none" />
              <div className="flex gap-3">
                <button type="button" disabled={reason.trim().length < 5 || busy} onClick={() => { setErr(null); reject.mutate(); }}
                  className="h-11 flex-1 rounded-[var(--radius-button,18px)] bg-[var(--alert)] font-semibold text-white disabled:opacity-50">
                  {reject.isPending ? <Spinner /> : t('review.sendBack')}
                </button>
                <button type="button" onClick={() => setRejecting(false)} className="h-11 px-5 font-semibold text-[var(--ink-muted)]">
                  {t('capture.cancel')}
                </button>
              </div>
            </div>
          )
        ) : (
          <p className="text-sm text-[var(--ink-muted)]">{t('review.ownRecord')}</p>
        )}
      </footer>
    </article>
  );
}
