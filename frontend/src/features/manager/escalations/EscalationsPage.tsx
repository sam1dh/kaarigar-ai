/**
 * W2 Escalations (/manager/escalations). Same layout as W1: list on the left, the selected question on the right.
 * Supervisors see every question Kaarigar couldn't settle, who it's with, and can reassign or close it.
 * Updates live through Supabase Realtime.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Spinner } from '../../capture/ui';
import {
  assignEscalation, closeEscalation, listExperts, managerEscalation, managerEscalationCount, managerEscalations,
  type EscFilter, type Escalation, type Source,
} from '../../assist/assistApi';
import { parseAnswerText } from '../../assist/parseAnswer';
import { ago, AnswerView, AudioMini, Notice } from '../../assist/parts';
import { useLiveRefresh } from '../../assist/realtime';
import SourceSheet from '../../assist/SourceSheet';

/** Sidebar badge: open escalations. */
export function useEscalationCount() {
  const q = useQuery({ queryKey: ['manager', 'escalations', 'count'], queryFn: managerEscalationCount, refetchInterval: 60_000 });
  useLiveRefresh('escalations', [['manager', 'escalations']]);
  return q.data?.open ?? 0;
}

const FILTERS: EscFilter[] = ['open', 'answered', 'closed', 'all'];

function StatusChip({ e }: { e: Escalation }) {
  const { t } = useTranslation();
  const cls = e.status === 'open'
    ? (e.assigned_to ? 'bg-[var(--safety-tint)] text-[var(--ink)]' : 'bg-[var(--alert-tint)] text-[var(--alert)]')
    : e.status === 'answered' ? 'bg-[var(--green-tint)] text-[var(--green-deep)]' : 'bg-[var(--surface)] text-[var(--ink-muted)] border border-[var(--line)]';
  const key = e.status === 'open' && !e.assigned_to ? 'unassigned' : e.status;
  return <span className={`inline-flex shrink-0 items-center rounded-full px-2.5 py-1 text-xs font-semibold ${cls}`}>{t(`escalations.status.${key}`)}</span>;
}

function Detail({ id }: { id: string }) {
  const { t, i18n } = useTranslation();
  const qc = useQueryClient();
  const [openSource, setOpenSource] = useState<Source | null>(null);
  const q = useQuery({ queryKey: ['manager', 'escalations', 'detail', id], queryFn: () => managerEscalation(id) });
  const experts = useQuery({ queryKey: ['manager', 'experts'], queryFn: listExperts, staleTime: 5 * 60_000 });
  const refresh = () => qc.invalidateQueries({ queryKey: ['manager', 'escalations'] });
  const assign = useMutation({ mutationFn: (uid: string) => assignEscalation(id, uid), onSuccess: refresh });
  const close = useMutation({ mutationFn: () => closeEscalation(id, 'not_needed'), onSuccess: refresh });
  const e = q.data;
  const parts = useMemo(() => {
    const txt = e?.kaarigar.answer_en ?? e?.kaarigar.answer_local ?? '';
    return parseAnswerText(txt === 'NO_ANSWER' ? '' : txt);
  }, [e]);

  if (q.isLoading) return <div className="p-6 text-[var(--ink-muted)]"><Spinner size={22} /></div>;
  if (!e) return <Notice tone="alert">{t('escalations.loadError')}</Notice>;
  const rec = e.reply.record;
  const askedBy = e.asked_by?.id;

  return (
    <article className="space-y-5 rounded-[var(--radius-card,22px)] bg-[var(--white)] p-6">
      <header className="flex flex-wrap items-start gap-4">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 text-sm text-[var(--ink-muted)]">
            {e.machine && <b className="text-[var(--green-deep)]" style={{ fontFamily: 'var(--font-heading)' }}>{e.machine.code}</b>}
            <span>{e.machine?.name}</span>
            <span>· {e.asked_by?.name} · {ago(e.created_at, i18n.language)}</span>
          </div>
          <h2 className="mt-1 text-2xl font-semibold leading-tight" style={{ fontFamily: 'var(--font-heading)' }}>
            {e.question.en ?? e.question.original}
          </h2>
          {e.question.original && e.question.original !== e.question.en && (
            <p className="mt-1 text-[var(--ink-muted)]" lang={e.question.language ?? undefined}>{e.question.original}</p>
          )}
        </div>
        <StatusChip e={e} />
      </header>

      {e.status === 'open' && (
        <div className="flex flex-wrap items-end gap-3 rounded-2xl bg-[var(--surface)] p-4">
          <label className="flex min-w-[240px] flex-1 flex-col gap-1 text-sm font-semibold">
            {t('escalations.assignTo')}
            <select value={e.assigned_to?.id ?? ''} disabled={assign.isPending || experts.isLoading}
              onChange={(ev) => ev.target.value && assign.mutate(ev.target.value)}
              className="min-h-[44px] rounded-xl border border-[var(--line)] bg-[var(--white)] px-3 font-normal focus:outline-none focus:ring-2 focus:ring-[var(--green)]">
              <option value="" disabled>{t('escalations.pickExpert')}</option>
              {(experts.data?.items ?? []).filter((x) => x.id !== askedBy).map((x) => (
                <option key={x.id} value={x.id}>
                  {x.name} · {t(`escalations.role.${x.role}`)} · {t('escalations.expertLoad', { open: x.open_assigned, records: x.approved_records })}
                </option>
              ))}
            </select>
          </label>
          <button type="button" onClick={() => close.mutate()} disabled={close.isPending}
            className="min-h-[44px] rounded-xl border border-[var(--line)] bg-[var(--white)] px-4 font-semibold focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--green)]">
            {t('escalations.close')}
          </button>
          {(assign.isError || close.isError) && <p role="alert" className="w-full text-sm text-[var(--alert)]">{t('escalations.actionError')}</p>}
        </div>
      )}

      {e.note && (
        <section>
          <h3 className="mb-1 text-sm font-semibold text-[var(--ink-muted)]">{t('escalations.note')}</h3>
          <p className="leading-relaxed">{e.note}</p>
        </section>
      )}

      <section>
        <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-[var(--ink-muted)]">
          {t('escalations.kaarigarAnswer')}
          {e.kaarigar.confidence != null && e.kaarigar.status === 'answered' && (
            <span className="font-normal">· {t('escalations.confidence', { pct: Math.round(e.kaarigar.confidence * 100) })}</span>
          )}
        </h3>
        {e.kaarigar.status === 'answered' && parts.steps.length > 0
          ? <AnswerView parts={parts} sources={e.kaarigar.sources} onOpenSource={setOpenSource} />
          : <Notice>{t(`escalations.kaarigar.${e.kaarigar.status ?? 'no_answer'}`)}</Notice>}
        {e.feedback && <p className="mt-2 text-sm">{t(`escalations.feedback.${e.feedback}`)}</p>}
      </section>

      <section>
        <h3 className="mb-2 text-sm font-semibold text-[var(--ink-muted)]">{t('escalations.expertReply')}</h3>
        {!e.reply.text && !rec && <Notice>{e.assigned_to ? t('escalations.waitingFor', { name: e.assigned_to.name }) : t('escalations.nobodyYet')}</Notice>}
        {e.reply.text && (
          <div className="rounded-2xl bg-[var(--surface)] p-4">
            <div className="mb-1 text-xs text-[var(--ink-muted)]">{e.replied_by?.name} · {ago(e.answered_at, i18n.language)}</div>
            <p className="leading-relaxed">{e.reply.text}</p>
          </div>
        )}
        {rec && (
          <div className="space-y-3 rounded-2xl bg-[var(--surface)] p-4">
            <div className="flex items-center justify-between gap-2 text-xs text-[var(--ink-muted)]">
              <span>{e.replied_by?.name ?? e.assigned_to?.name} · {t('escalations.voiceReply')}</span>
              <span>{t(`escalations.recordStatus.${rec.status}`, { defaultValue: rec.status })}</span>
            </div>
            {rec.audio_url && <AudioMini src={rec.audio_url} label={t('escalations.listen')} />}
            {rec.fields.fix && <p className="font-semibold">{rec.fields.fix}</p>}
            {(rec.fields.steps ?? []).length > 0 && (
              <ol className="list-decimal space-y-1 pl-5">{(rec.fields.steps ?? []).map((s, i) => <li key={i}>{s}</li>)}</ol>
            )}
            {rec.status === 'pending' && <p className="text-sm text-[var(--manual)]">{t('escalations.inReviewQueue')}</p>}
          </div>
        )}
      </section>
      <SourceSheet source={openSource} onClose={() => setOpenSource(null)} />
    </article>
  );
}

export default function EscalationsPage() {
  const { t, i18n } = useTranslation();
  const [filter, setFilter] = useState<EscFilter>('open');
  const q = useQuery({ queryKey: ['manager', 'escalations', 'list', filter], queryFn: () => managerEscalations(filter), refetchInterval: 60_000 });
  useLiveRefresh('escalations', [['manager', 'escalations']]);
  const items = q.data?.items ?? [];
  const [selected, setSelected] = useState<string | null>(null);

  useEffect(() => {
    if (!items.length) setSelected(null);
    else if (!selected || !items.some((i) => i.id === selected)) setSelected(items[0].id);
  }, [items, selected]);

  const counts = q.data?.counts;
  return (
    <div className="flex h-full min-h-0 flex-col" style={{ fontFamily: 'var(--font-body)' }}>
      <div className="mb-4 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-[32px] font-semibold leading-tight" style={{ fontFamily: 'var(--font-heading)' }}>{t('escalations.title')}</h1>
          <p className="text-[var(--ink-muted)]">
            {counts ? t('escalations.summary', { open: counts.open, unassigned: counts.unassigned }) : t('escalations.subtitle')}
          </p>
        </div>
        <div role="tablist" className="flex gap-1 rounded-xl border border-[var(--line)] bg-[var(--white)] p-1">
          {FILTERS.map((f) => (
            <button key={f} type="button" role="tab" aria-selected={filter === f} onClick={() => setFilter(f)}
              className={`min-h-[36px] rounded-lg px-3 text-sm ${filter === f ? 'bg-[var(--green)] font-semibold text-[var(--white)]' : 'text-[var(--ink)]'}`}>
              {t(`escalations.filter.${f}`)}
            </button>
          ))}
        </div>
      </div>

      {q.isLoading ? (
        <div className="text-[var(--ink-muted)]"><Spinner size={24} /></div>
      ) : !items.length ? (
        <div className="rounded-[var(--radius-card,22px)] bg-[var(--surface)] p-8 text-[var(--ink-muted)]">{t(`escalations.empty.${filter}`)}</div>
      ) : (
        <div className="grid min-h-0 flex-1 grid-cols-[minmax(280px,380px)_1fr] gap-5">
          <ul className="min-h-0 space-y-2 overflow-y-auto pr-1" aria-label={t('escalations.title')}>
            {items.map((it) => (
              <li key={it.id}>
                <button type="button" onClick={() => setSelected(it.id)} aria-current={selected === it.id}
                  className={`w-full rounded-2xl border px-4 py-3 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--green)] ${selected === it.id ? 'border-[var(--green)] bg-[var(--white)]' : 'border-transparent bg-[var(--surface)] hover:border-[var(--line)]'}`}>
                  <div className="flex items-center justify-between gap-2">
                    <span className="flex items-center gap-2">
                      {it.machine && <b className="text-[var(--green-deep)]" style={{ fontFamily: 'var(--font-heading)' }}>{it.machine.code}</b>}
                      <span className="text-xs text-[var(--ink-faint)]">{ago(it.created_at, i18n.language)}</span>
                    </span>
                    <StatusChip e={it} />
                  </div>
                  <div className="mt-1 line-clamp-2 font-semibold leading-snug">{it.question.en ?? it.question.original}</div>
                  <div className="mt-1 text-xs text-[var(--ink-muted)]">
                    {it.asked_by?.name}
                    {it.assigned_to && <> → {it.assigned_to.name}</>}
                    {it.answer_status === 'no_answer' && <> · {t('escalations.kaarigar.no_answer_short')}</>}
                    {it.feedback === 'not_fixed' && <> · {t('escalations.feedback.not_fixed_short')}</>}
                  </div>
                </button>
              </li>
            ))}
          </ul>
          <div className="min-h-0 overflow-y-auto">{selected && <Detail key={selected} id={selected} />}</div>
        </div>
      )}
    </div>
  );
}
