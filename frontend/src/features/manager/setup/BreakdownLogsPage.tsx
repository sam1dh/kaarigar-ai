/**
 * W5 Breakdown logs (/manager/setup/logs). Plant admins only. Uses Phase 1's import endpoints.
 * Upload the plant's Excel/CSV breakdown register → check which column is which (Kaarigar suggests it) →
 * import → see what was skipped and why. Each row becomes a history source (H) for answers.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  confirmImport, errorCode, errorMessage, getImport, getJob, importHistory, LOG_FIELDS, maintenanceLogs, uploadLog,
  type LogAnalysis, type LogField, type Mapping,
} from '../manageApi';
import { Banner, Btn, Card, Chip, dateFmt, Empty, heading, inputCls, Page, Spinner } from '../ui/kit';

const REQUIRED: LogField[] = ['machine_code', 'fault'];
const MAX_MB = 5;    // keep in step with Phase 1's MAX_LOG_MB

type Step = 'upload' | 'map' | 'importing' | 'result';

/** Phase 1 may send sample rows as arrays (column order) or objects (by column name). */
function rowsByColumn(a: LogAnalysis): Record<string, unknown>[] {
  return (a.sample_rows as unknown[]).map((r) =>
    Array.isArray(r) ? Object.fromEntries(a.columns.map((c, i) => [c, r[i]])) : (r as Record<string, unknown>));
}
const cell = (v: unknown) => (v === null || v === undefined ? '' : String(v));

function StepDots({ step }: { step: Step }) {
  const { t } = useTranslation();
  const order: Step[] = ['upload', 'map', 'importing', 'result'];
  const at = order.indexOf(step);
  return (
    <ol className="flex flex-wrap gap-2 text-sm" aria-label={t('manage.logs.steps')}>
      {(['upload', 'map', 'result'] as Step[]).map((s, i) => {
        const idx = order.indexOf(s);
        const state = at > idx || (s === 'result' && step === 'result') ? 'done' : at === idx || (s === 'result' && step === 'importing') ? 'now' : 'next';
        return (
          <li key={s} aria-current={state === 'now' ? 'step' : undefined}
            className={`flex items-center gap-2 rounded-full px-3 py-1 ${state === 'now' ? 'bg-[var(--green)] text-[var(--white)]' : state === 'done' ? 'bg-[var(--green-tint)] text-[var(--green-deep)]' : 'bg-[var(--surface)] text-[var(--ink-muted)]'}`}>
            <span className="tabular-nums font-semibold">{i + 1}</span>{t(`manage.logs.step.${s}`)}
          </li>
        );
      })}
    </ol>
  );
}

function MappingEditor({ a, mapping, setMapping }: { a: LogAnalysis; mapping: Mapping; setMapping: (m: Mapping) => void }) {
  const { t } = useTranslation();
  const rows = useMemo(() => rowsByColumn(a), [a]);
  const used = new Set(Object.values(mapping).filter(Boolean));
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-x-5 gap-y-3">
        {LOG_FIELDS.map((f) => {
          const col = mapping[f];
          const example = col ? rows.map((r) => cell(r[col])).find(Boolean) : '';
          const id = `map-${f}`;
          return (
            <div key={f} className="space-y-1">
              <label htmlFor={id} className="flex items-center gap-2 text-sm font-semibold">
                {t(`manage.logs.field.${f}`)}
                {REQUIRED.includes(f) && <span className="text-xs font-normal text-[var(--alert)]">{t('manage.logs.required')}</span>}
              </label>
              <select id={id} className={inputCls} value={col ?? ''} onChange={(e) => setMapping({ ...mapping, [f]: e.target.value || null })}>
                <option value="">{t('manage.logs.notInFile')}</option>
                {a.columns.map((c) => <option key={c} value={c} disabled={used.has(c) && c !== col}>{c}</option>)}
              </select>
              <p className="truncate text-xs text-[var(--ink-muted)]">{example ? t('manage.logs.example', { value: example }) : ' '}</p>
            </div>
          );
        })}
      </div>
      <div>
        <p className="mb-2 text-sm font-semibold">{t('manage.logs.preview', { count: rows.length, total: a.total_rows })}</p>
        <div className="overflow-x-auto rounded-xl border border-[var(--line)]">
          <table className="w-full text-left text-sm">
            <thead className="bg-[var(--surface)] text-xs">
              <tr>{a.columns.map((c) => {
                const f = LOG_FIELDS.find((x) => mapping[x] === c);
                return (
                  <th key={c} scope="col" className={`whitespace-nowrap px-3 py-2 font-semibold ${f ? 'text-[var(--green-deep)]' : 'text-[var(--ink-faint)]'}`}>
                    {c}{f && <div className="font-normal">→ {t(`manage.logs.field.${f}`)}</div>}
                  </th>
                );
              })}</tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i} className="border-t border-[var(--line)]">
                  {a.columns.map((c) => <td key={c} className={`max-w-[220px] truncate px-3 py-2 ${used.has(c) ? '' : 'text-[var(--ink-faint)]'}`}>{cell(r[c])}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-2 text-xs text-[var(--ink-muted)]">{t('manage.logs.otherColumns')}</p>
      </div>
    </div>
  );
}

function ImportFlow() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const fileRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [analysis, setAnalysis] = useState<LogAnalysis | null>(null);
  const [mapping, setMapping] = useState<Mapping | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const tooBig = !!file && file.size > MAX_MB * 1024 * 1024;

  const up = useMutation({
    mutationFn: (force: boolean) => uploadLog(file!, force),
    onSuccess: (a) => { setAnalysis(a); setMapping({ ...a.suggested_mapping }); },
  });
  const confirm = useMutation({ mutationFn: () => confirmImport(analysis!.import_id, mapping!), onSuccess: (r) => setJobId(r.job_id) });
  const job = useQuery({
    queryKey: ['manage', 'job', jobId], queryFn: () => getJob(jobId!), enabled: !!jobId,
    refetchInterval: (q) => (q.state.data && ['done', 'failed'].includes(q.state.data.status) ? false : 1500),
  });
  const finished = job.data?.status === 'done' || job.data?.status === 'failed';
  const result = useQuery({ queryKey: ['manage', 'import', analysis?.import_id], queryFn: () => getImport(analysis!.import_id), enabled: !!analysis && finished });
  useEffect(() => { if (finished) qc.invalidateQueries({ queryKey: ['manage', 'logs'] }); }, [finished, qc]);

  const step: Step = !analysis ? 'upload' : !jobId ? 'map' : !finished ? 'importing' : 'result';
  const missing = mapping ? REQUIRED.filter((f) => !mapping[f]) : REQUIRED;
  const dup = up.isError && errorCode(up.error) === 'already_imported';
  const restart = () => {
    setFile(null); setAnalysis(null); setMapping(null); setJobId(null); up.reset(); confirm.reset();
    if (fileRef.current) fileRef.current.value = '';
  };

  return (
    <Card className="space-y-5 p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-xl font-semibold" style={heading}>{t('manage.logs.importTitle')}</h2>
        <StepDots step={step} />
      </div>

      {step === 'upload' && (
        <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); if (file && !tooBig) up.mutate(false); }}>
          <p className="text-[var(--ink-muted)]">{t('manage.logs.uploadHelp')}</p>
          <input ref={fileRef} type="file" accept=".xlsx,.csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,text/csv" aria-label={t('manage.logs.file')}
            className="block w-full text-sm file:mr-3 file:min-h-[38px] file:rounded-lg file:border-0 file:bg-[var(--green-tint)] file:px-3 file:font-semibold file:text-[var(--green-deep)]"
            onChange={(e) => { setFile(e.target.files?.[0] ?? null); up.reset(); }} />
          {tooBig && <Banner tone="alert">{t('manage.logs.tooBig', { mb: MAX_MB })}</Banner>}
          {dup ? (
            <Banner tone="safety" action={<Btn small kind="primary" busy={up.isPending} onClick={() => up.mutate(true)}>{t('manage.logs.importAgain')}</Btn>}>{t('manage.logs.duplicate')}</Banner>
          ) : up.isError ? <Banner tone="alert">{errorMessage(up.error) ?? t('manage.errors.generic')}</Banner> : null}
          {!dup && <Btn type="submit" kind="primary" busy={up.isPending} disabled={!file || tooBig}>{t('manage.logs.read')}</Btn>}
        </form>
      )}

      {step === 'map' && analysis && mapping && (
        <div className="space-y-5">
          <Banner tone="info">
            {t('manage.logs.found', { rows: analysis.total_rows, header: analysis.header_row })}{' '}
            {analysis.mapping_source === 'llm' ? t('manage.logs.suggestedAi') : t('manage.logs.suggestedRules')}
          </Banner>
          <MappingEditor a={analysis} mapping={mapping} setMapping={setMapping} />
          {confirm.isError && <Banner tone="alert">{errorMessage(confirm.error) ?? t('manage.errors.generic')}</Banner>}
          <div className="flex flex-wrap items-center justify-end gap-3">
            {missing.length > 0 && <span className="text-sm text-[var(--alert)]">{t('manage.logs.pickRequired', { fields: missing.map((f) => t(`manage.logs.field.${f}`)).join(', ') })}</span>}
            <Btn onClick={restart}>{t('manage.logs.otherFile')}</Btn>
            <Btn kind="primary" busy={confirm.isPending} disabled={missing.length > 0} onClick={() => confirm.mutate()}>{t('manage.logs.import', { count: analysis.total_rows })}</Btn>
          </div>
        </div>
      )}

      {step === 'importing' && (
        <div className="space-y-2" role="status">
          <div className="flex justify-between text-sm"><span>{t('manage.logs.importing')}</span><span className="tabular-nums">{Math.round(job.data?.progress ?? 0)}%</span></div>
          <div className="h-2 overflow-hidden rounded-full bg-[var(--surface)]"><div className="h-full rounded-full bg-[var(--green)] transition-[width] duration-500" style={{ width: `${Math.round(job.data?.progress ?? 0)}%` }} /></div>
        </div>
      )}

      {step === 'result' && (
        <div className="space-y-4">
          {job.data?.status === 'failed' ? <Banner tone="alert">{job.data.error ?? t('manage.logs.failed')}</Banner> : result.isLoading ? <Spinner /> : result.data && (
            <>
              <div className="grid grid-cols-2 gap-3">
                <div className="rounded-2xl bg-[var(--green-tint)] p-4"><div className="text-[30px] font-semibold leading-none tabular-nums text-[var(--green-deep)]" style={heading}>{result.data.rows_ok}</div><div className="mt-1 text-sm font-semibold">{t('manage.logs.imported')}</div></div>
                <div className="rounded-2xl bg-[var(--surface)] p-4"><div className="text-[30px] font-semibold leading-none tabular-nums" style={heading}>{result.data.rows_skipped}</div><div className="mt-1 text-sm font-semibold">{t('manage.logs.skipped')}</div></div>
              </div>
              {!!result.data.skipped?.length && (
                <details className="rounded-xl border border-[var(--line)] p-3" open={result.data.skipped.length <= 6}>
                  <summary className="cursor-pointer text-sm font-semibold">{t('manage.logs.whySkipped')}</summary>
                  <ul className="mt-2 max-h-[220px] space-y-1 overflow-y-auto text-sm">
                    {result.data.skipped.map((s, i) => <li key={i}><span className="tabular-nums text-[var(--ink-muted)]">{t('manage.logs.row', { n: s.row })}</span> {s.reason}</li>)}
                  </ul>
                  <p className="mt-2 text-xs text-[var(--ink-muted)]">{t('manage.logs.unknownMachineHint')}</p>
                </details>
              )}
            </>
          )}
          <Btn onClick={restart}>{t('manage.logs.another')}</Btn>
        </div>
      )}
    </Card>
  );
}

export default function BreakdownLogsPage() {
  const { t, i18n } = useTranslation();
  const [machine, setMachine] = useState('');
  const history = useQuery({ queryKey: ['manage', 'logs', 'imports'], queryFn: importHistory });
  const logs = useQuery({ queryKey: ['manage', 'logs', 'entries', machine.trim()], queryFn: () => maintenanceLogs(machine.trim() || undefined), placeholderData: (p) => p });

  return (
    <Page title={t('manage.logs.title')} subtitle={t('manage.logs.subtitle')}>
      <div className="grid min-h-0 grid-cols-[minmax(0,1fr)_380px] items-start gap-5">
        <ImportFlow />
        <div className="space-y-5">
          <Card className="p-5">
            <h2 className="mb-3 font-semibold" style={heading}>{t('manage.logs.history')}</h2>
            {history.isLoading ? <Spinner /> : !(history.data?.items.length) ? <p className="text-sm text-[var(--ink-muted)]">{t('manage.logs.noHistory')}</p> : (
              <ul className="space-y-2.5 text-sm">
                {history.data.items.map((h) => (
                  <li key={h.id} className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <div className="truncate font-semibold">{h.file_name ?? t('manage.logs.file')}</div>
                      <div className="text-[var(--ink-muted)]">{[dateFmt(h.created_at, i18n.language), h.created_by].filter(Boolean).join(' · ')}</div>
                    </div>
                    {h.status === 'done' ? <span className="shrink-0 tabular-nums text-[var(--ink-muted)]">{t('manage.logs.okSkipped', { ok: h.rows_ok, skipped: h.rows_skipped })}</span>
                      : <Chip tone={h.status === 'failed' ? 'alert' : 'plain'}>{t(`manage.logs.importStatus.${h.status}`, { defaultValue: h.status })}</Chip>}
                  </li>
                ))}
              </ul>
            )}
          </Card>
          <Card className="p-5">
            <div className="mb-3 flex items-center justify-between gap-2">
              <h2 className="font-semibold" style={heading}>{t('manage.logs.entries')}</h2>
              <input className={`${inputCls} !min-h-[34px] !w-[110px] text-sm uppercase`} value={machine} onChange={(e) => setMachine(e.target.value)} placeholder="HP-07" aria-label={t('manage.knowledge.machine')} />
            </div>
            {logs.isLoading ? <Spinner /> : !(logs.data?.items.length) ? <Empty title={t('manage.logs.noEntries')} /> : (
              <ul className="max-h-[420px] space-y-3 overflow-y-auto text-sm">
                {logs.data.items.map((l) => (
                  <li key={l.id}>
                    <div className="flex items-center gap-2"><b className="text-[var(--history)]" style={heading}>{l.machine}</b><span className="text-[var(--ink-muted)]">{dateFmt(l.date, i18n.language)}</span>{l.downtime_min != null && <span className="ml-auto tabular-nums text-[var(--ink-muted)]">{t('manage.knowledge.downtime', { count: l.downtime_min })}</span>}</div>
                    <div className="font-semibold leading-snug">{l.fault}</div>
                    {l.action && <div className="text-[var(--ink-muted)]">{l.action}</div>}
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
      </div>
    </Page>
  );
}
