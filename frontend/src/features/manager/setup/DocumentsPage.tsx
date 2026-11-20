/**
 * W4 Documents (/manager/setup/documents). Plant admins only. Uses Phase 1's endpoints.
 * Upload a manual, SOP or safety sheet for a machine model → Kaarigar reads it (job with progress) → its sections
 * become answer sources (M). Scanned pages without text are flagged so the admin knows what isn't searchable.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  deleteDocument, errorCode, errorMessage, getJob, listDocuments, listModels, uploadDocument, type DocumentRow, type Job,
} from '../manageApi';
import { Banner, Btn, Card, Chip, Confirm, dateFmt, Empty, Field, heading, inputCls, Page, Spinner } from '../ui/kit';

const KEY = ['manage', 'documents'];
const MAX_MB = 25;   // keep in step with Phase 1's MAX_PDF_MB

function useJob(jobId: string | null) {
  return useQuery({
    queryKey: ['manage', 'job', jobId],
    queryFn: () => getJob(jobId!),
    enabled: !!jobId,
    refetchInterval: (q) => (q.state.data && ['done', 'failed'].includes(q.state.data.status) ? false : 1500),
  });
}

function StatusChip({ d }: { d: DocumentRow }) {
  const { t } = useTranslation();
  if (d.status === 'ready') return d.quality_notes ? <Chip tone="safety">{t('manage.documents.status.readyCheck')}</Chip> : <Chip tone="green">{t('manage.documents.status.ready')}</Chip>;
  if (d.status === 'failed') return <Chip tone="alert">{t('manage.documents.status.failed')}</Chip>;
  return <Chip tone="manual"><Spinner size={12} /> {t('manage.documents.status.reading')}</Chip>;
}

function Progress({ job }: { job: Job | undefined }) {
  const { t } = useTranslation();
  const pct = Math.round(job?.progress ?? 0);
  return (
    <div className="space-y-1.5" role="status">
      <div className="flex justify-between text-sm"><span>{t(`manage.documents.job.${job?.status ?? 'queued'}`)}</span><span className="tabular-nums">{pct}%</span></div>
      <div className="h-2 overflow-hidden rounded-full bg-[var(--surface)]" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
        <div className="h-full rounded-full bg-[var(--green)] transition-[width] duration-500" style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function UploadCard() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const models = useQuery({ queryKey: ['manage', 'models'], queryFn: listModels, staleTime: 60_000 });
  const fileRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState('');
  const [type, setType] = useState('manual');
  const [modelId, setModelId] = useState('');
  const [jobId, setJobId] = useState<string | null>(null);
  const [tooBig, setTooBig] = useState(false);
  const job = useJob(jobId);
  const up = useMutation({
    mutationFn: (replace: boolean) => uploadDocument({ file: file!, title: title.trim(), type, model_id: modelId }, replace),
    onSuccess: (r) => { setJobId(r.job_id); qc.invalidateQueries({ queryKey: KEY }); },
  });
  const status = job.data?.status;
  useEffect(() => {
    if (status === 'done' || status === 'failed') qc.invalidateQueries({ queryKey: KEY });
  }, [status, qc]);
  const reset = () => { setFile(null); setTitle(''); setJobId(null); up.reset(); if (fileRef.current) fileRef.current.value = ''; };
  const dup = up.isError && errorCode(up.error) === 'already_uploaded';
  const busy = up.isPending || (!!jobId && status !== 'done' && status !== 'failed');
  const valid = !!file && title.trim().length >= 2 && !!modelId && !tooBig;

  return (
    <Card className="space-y-4 p-6">
      <h2 className="text-xl font-semibold" style={heading}>{t('manage.documents.upload')}</h2>
      {jobId ? (
        <div className="space-y-4">
          <p className="font-semibold">{title}</p>
          {status === 'done' ? <Banner tone="ok">{t('manage.documents.job.doneText')}</Banner>
            : status === 'failed' ? <Banner tone="alert">{job.data?.error ?? t('manage.documents.job.failedText')}</Banner>
            : <Progress job={job.data} />}
          {(status === 'done' || status === 'failed') && <Btn onClick={reset}>{t('manage.documents.another')}</Btn>}
        </div>
      ) : (
        <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); if (valid) up.mutate(false); }}>
          <Field label={t('manage.documents.form.file')} hint={tooBig ? undefined : t('manage.documents.form.fileHint', { mb: MAX_MB })} error={tooBig ? t('manage.documents.form.tooBig', { mb: MAX_MB }) : undefined}>
            {(id, d) => (
              <input id={id} aria-describedby={d} ref={fileRef} type="file" accept="application/pdf,.pdf"
                className="block w-full text-sm file:mr-3 file:min-h-[38px] file:rounded-lg file:border-0 file:bg-[var(--green-tint)] file:px-3 file:font-semibold file:text-[var(--green-deep)]"
                onChange={(e) => {
                  const f = e.target.files?.[0] ?? null;
                  setFile(f);
                  setTooBig(!!f && f.size > MAX_MB * 1024 * 1024);
                  if (f && !title) setTitle(f.name.replace(/\.pdf$/i, '').replace(/[_-]+/g, ' '));
                  up.reset();
                }} />
            )}
          </Field>
          <Field label={t('manage.documents.form.title')}>
            {(id) => <input id={id} className={inputCls} value={title} onChange={(e) => setTitle(e.target.value)} maxLength={120} required />}
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label={t('manage.documents.form.type')}>
              {(id) => (
                <select id={id} className={inputCls} value={type} onChange={(e) => setType(e.target.value)}>
                  {['manual', 'sop', 'safety'].map((x) => <option key={x} value={x}>{t(`manage.documents.type.${x}`)}</option>)}
                </select>
              )}
            </Field>
            <Field label={t('manage.documents.form.model')} hint={!models.data?.length ? t('manage.documents.form.noModels') : undefined}>
              {(id, d) => (
                <select id={id} aria-describedby={d} className={inputCls} value={modelId} onChange={(e) => setModelId(e.target.value)} required>
                  <option value="">{t('manage.documents.form.pickModel')}</option>
                  {(models.data ?? []).map((m) => <option key={m.id} value={m.id}>{m.model}{m.machines?.length ? ` (${m.machines.join(', ')})` : ''}</option>)}
                </select>
              )}
            </Field>
          </div>
          {dup ? (
            <Banner tone="safety" action={<><Btn small onClick={() => up.reset()}>{t('manage.common.cancel')}</Btn><Btn small kind="primary" busy={up.isPending} onClick={() => up.mutate(true)}>{t('manage.documents.replace')}</Btn></>}>
              {t('manage.documents.duplicate')}
            </Banner>
          ) : up.isError ? <Banner tone="alert">{errorMessage(up.error) ?? t('manage.errors.generic')}</Banner> : null}
          {!dup && <Btn type="submit" kind="primary" busy={busy} disabled={!valid}>{t('manage.documents.form.submit')}</Btn>}
        </form>
      )}
    </Card>
  );
}

export default function DocumentsPage() {
  const { t, i18n } = useTranslation();
  const qc = useQueryClient();
  const [del, setDel] = useState<DocumentRow | null>(null);
  const q = useQuery({
    queryKey: KEY, queryFn: listDocuments,
    refetchInterval: (query) => ((query.state.data ?? []).some((d) => !['ready', 'failed'].includes(d.status)) ? 3000 : false),
  });
  const remove = useMutation({ mutationFn: (id: string) => deleteDocument(id), onSuccess: () => { setDel(null); qc.invalidateQueries({ queryKey: KEY }); } });
  const docs = q.data ?? [];

  return (
    <Page title={t('manage.documents.title')} subtitle={t('manage.documents.subtitle')}>
      <div className="grid min-h-0 grid-cols-[400px_1fr] items-start gap-5">
        <UploadCard />
        <div className="min-w-0">
          {q.isLoading ? <Spinner size={24} /> : q.isError ? <Banner tone="alert">{t('manage.errors.load')}</Banner> : !docs.length ? (
            <Empty title={t('manage.documents.empty')}>{t('manage.documents.emptyHint')}</Empty>
          ) : (
            <ul className="space-y-3">
              {docs.map((d) => (
                <li key={d.id}>
                  <Card className="p-5">
                    <div className="flex flex-wrap items-start gap-3">
                      <div className="min-w-0 flex-1">
                        <div className="font-semibold">{d.title}</div>
                        <div className="text-sm text-[var(--ink-muted)]">
                          {[t(`manage.documents.type.${d.type}`, { defaultValue: d.type }), d.model, d.pages ? t('manage.documents.pages', { count: d.pages }) : null,
                            d.chunks ? t('manage.documents.sections', { count: d.chunks }) : null, dateFmt(d.created_at, i18n.language)].filter(Boolean).join(' · ')}
                        </div>
                      </div>
                      <StatusChip d={d} />
                      <Btn small kind="ghost" className="!text-[var(--alert)]" onClick={() => setDel(d)}>{t('manage.documents.delete')}</Btn>
                    </div>
                    {d.status === 'failed' && d.error && <div className="mt-3"><Banner tone="alert">{d.error}</Banner></div>}
                    {d.quality_notes && <div className="mt-3"><Banner tone="safety">{d.quality_notes}</Banner></div>}
                  </Card>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
      {del && (
        <Confirm open danger onClose={() => { setDel(null); remove.reset(); }} busy={remove.isPending}
          title={t('manage.documents.confirmDelete.title')} confirmLabel={t('manage.documents.confirmDelete.cta')}
          onConfirm={() => remove.mutate(del.id)}
          body={<>
            <p className="font-semibold">{del.title}</p>
            <p className="mt-2">{t('manage.documents.confirmDelete.body')}</p>
            {remove.isError && <div className="mt-3"><Banner tone="alert">{errorMessage(remove.error) ?? t('manage.errors.generic')}</Banner></div>}
          </>} />
      )}
    </Page>
  );
}
