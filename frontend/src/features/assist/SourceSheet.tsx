/** Opens when a source chip is tapped: the expert's note (with voice), the manual page, or the history entry. */
import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Spinner } from '../capture/ui';
import { getSource, type LogSource, type ManualSource, type RecordSource, type Source } from './assistApi';
import { AudioMini, LABEL_TONE, Notice, Sheet } from './parts';

function fmtDate(iso: string | null, lang: string) {
  if (!iso) return '';
  return new Date(iso).toLocaleDateString(lang, { day: 'numeric', month: 'short', year: 'numeric' });
}

function Row({ label, value }: { label: string; value: string | null | undefined }) {
  if (!value) return null;
  return (
    <div>
      <dt className="text-xs font-semibold text-[var(--ink-muted)]">{label}</dt>
      <dd className="mt-0.5 leading-relaxed">{value}</dd>
    </div>
  );
}

function RecordBody({ r }: { r: RecordSource }) {
  const { t, i18n } = useTranslation();
  const [english, setEnglish] = useState(false);
  const f = !english && r.local ? r.local : r.fields;
  const steps = (f.steps ?? []).filter(Boolean);
  return (
    <div className="space-y-4">
      <p className="text-sm text-[var(--ink-muted)]">
        {t('assist.source.recordBy', { name: r.author.name ?? '', date: fmtDate(r.date, i18n.language) })}
        {r.approved_by && <> · {t('assist.source.approvedBy', { name: r.approved_by })}</>}
      </p>
      {r.audio_url && <AudioMini src={r.audio_url} label={t('assist.source.expertVoice')} />}
      {f.safety_note && (
        <Notice tone="info"><b className="mr-1 text-[var(--ink)]">{t('assist.answer.safety')}</b><span className="text-[var(--ink)]">{f.safety_note}</span></Notice>
      )}
      <dl className="space-y-3">
        <Row label={t('assist.source.problem')} value={f.symptom} />
        <Row label={t('assist.source.cause')} value={f.cause} />
        <Row label={t('assist.source.fix')} value={f.fix} />
      </dl>
      {steps.length > 0 && (
        <ol className="list-decimal space-y-1 pl-5 leading-relaxed">{steps.map((s, i) => <li key={i}>{s}</li>)}</ol>
      )}
      {r.local && (
        <button type="button" onClick={() => setEnglish((v) => !v)} className="text-sm font-semibold text-[var(--green-deep)] underline underline-offset-4">
          {english ? t('assist.source.showMine') : t('assist.source.showEnglish')}
        </button>
      )}
    </div>
  );
}

function ManualBody({ m }: { m: ManualSource }) {
  const { t } = useTranslation();
  return (
    <div className="space-y-3">
      <p className="text-sm text-[var(--ink-muted)]">{m.model ? `${m.model} · ` : ''}{m.page ? t('assist.source.page', { page: m.page }) : ''}</p>
      {m.sections.length === 0 && <Notice>{t('assist.source.noText')}</Notice>}
      {m.sections.map((s, i) => (
        <div key={i} className="rounded-2xl bg-[var(--white)] px-4 py-3">
          {s.section && <div className="mb-1 text-sm font-semibold">{s.section}</div>}
          <p className="whitespace-pre-line text-[15px] leading-relaxed">{s.text}</p>
        </div>
      ))}
      {m.pdf_url && (
        <a href={m.pdf_url} target="_blank" rel="noopener noreferrer"
          className="inline-flex min-h-[48px] items-center rounded-[var(--radius-button,18px)] border border-[var(--line)] bg-[var(--surface)] px-4 font-semibold">
          {t('assist.source.openPdf')}
        </a>
      )}
    </div>
  );
}

function LogBody({ l }: { l: LogSource }) {
  const { t, i18n } = useTranslation();
  return (
    <dl className="space-y-3">
      <Row label={t('assist.source.date')} value={fmtDate(l.date, i18n.language)} />
      <Row label={t('assist.source.problem')} value={l.fault} />
      <Row label={t('assist.source.whatWasDone')} value={l.action} />
      <Row label={t('assist.source.downtime')} value={l.downtime_min != null ? t('assist.source.minutes', { count: l.downtime_min }) : null} />
      <Row label={t('assist.source.technician')} value={l.technician} />
    </dl>
  );
}

export default function SourceSheet({ source, onClose }: { source: Source | null; onClose: () => void }) {
  const { t } = useTranslation();
  const q = useQuery({
    queryKey: ['assist', 'source', source?.source_type, source?.source_id, source?.page],
    queryFn: () => getSource(source as Source),
    enabled: !!source,
    staleTime: 10 * 60_000,
  });
  const tone = source ? LABEL_TONE[source.label] : LABEL_TONE.M;
  return (
    <Sheet open={!!source} onClose={onClose} title={source && (
      <span className="flex items-center gap-2">
        <span className="inline-flex h-6 min-w-[2rem] items-center justify-center rounded-full px-2 text-xs font-bold"
          style={{ background: tone.bg, color: tone.fg }}>{source.ref}</span>
        <span>{t(`assist.source.kind.${source.label}`)}</span>
      </span>
    )}>
      {source && <p className="mb-3 font-semibold leading-snug">{source.title}</p>}
      {q.isLoading && <div className="py-6 text-[var(--ink-muted)]"><Spinner size={22} /></div>}
      {q.isError && <Notice tone="alert">{t('assist.source.error')}</Notice>}
      {q.data?.type === 'record' && <RecordBody r={q.data} />}
      {q.data?.type === 'manual' && <ManualBody m={q.data} />}
      {q.data?.type === 'log' && <LogBody l={q.data} />}
    </Sheet>
  );
}
