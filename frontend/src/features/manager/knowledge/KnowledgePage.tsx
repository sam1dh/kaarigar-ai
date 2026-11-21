/**
 * W6 Knowledge base (/manager/knowledge). Any supervisor.
 * Everything Kaarigar answers from, in one list: approved expert repairs (E), manual sections (M) and breakdown
 * history (H), with how many answers used each. Open any item to read it; archive an outdated repair so Kaarigar
 * stops using it (restore puts it back).
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useDeferredValue, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import type { Source } from '../../assist/assistApi';
import { LABEL_TONE } from '../../assist/parts';
import SourceSheet from '../../assist/SourceSheet';
import { archiveRecord, errorMessage, knowledgeItems, knowledgeStats, restoreRecord, type Kind, type KnowledgeItem } from '../manageApi';
import { Banner, Btn, Card, Chip, Confirm, dateFmt, Empty, heading, inputCls, Page, Search, Segmented, Spinner } from '../ui/kit';

const KEY = ['manage', 'knowledge'];

function Stat({ value, label, note }: { value: string | number; label: string; note?: string }) {
  return (
    <Card className="px-5 py-4">
      <div className="text-[30px] font-semibold leading-none tabular-nums" style={heading}>{value}</div>
      <div className="mt-1.5 text-sm font-semibold">{label}</div>
      {note && <div className="text-xs text-[var(--ink-muted)]">{note}</div>}
    </Card>
  );
}

function KindBadge({ kind }: { kind: Kind }) {
  const tone = LABEL_TONE[kind];
  return <span className="inline-grid h-7 w-7 shrink-0 place-items-center rounded-full text-xs font-bold" style={{ background: tone.bg, color: tone.fg }} aria-hidden>{kind}</span>;
}

function toSource(it: KnowledgeItem): Source {
  return { ref: it.kind, label: it.kind, source_type: it.source_type, source_id: it.id, chunk_id: null, title: it.title, page: null, same_machine: false, seed_key: null, snippet: '' };
}

function Meta({ it }: { it: KnowledgeItem }) {
  const { t, i18n } = useTranslation();
  const bits: string[] = [];
  if (it.machine) bits.push(it.machine);
  if (it.kind === 'E') {
    if (it.author) bits.push(t('manage.knowledge.by', { name: it.author }));
    if (it.approved_by) bits.push(t('manage.knowledge.approvedBy', { name: it.approved_by }));
    if (it.origin === 'escalation') bits.push(t('manage.knowledge.fromQuestion'));
  }
  if (it.kind === 'M') {
    if (it.model) bits.push(it.model);
    if (it.sections) bits.push(t('manage.knowledge.sections', { count: it.sections }));
  }
  if (it.kind === 'H') {
    if (it.technician) bits.push(it.technician);
    if (it.downtime_min != null) bits.push(t('manage.knowledge.downtime', { count: it.downtime_min }));
  }
  if (it.date) bits.push(dateFmt(it.date, i18n.language));
  return <div className="text-sm text-[var(--ink-muted)]">{bits.join(' · ')}</div>;
}

export default function KnowledgePage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [kind, setKind] = useState<'all' | Kind>('all');
  const [machine, setMachine] = useState('');
  const [search, setSearch] = useState('');
  const [sort, setSort] = useState<'recent' | 'used'>('recent');
  const [archived, setArchived] = useState(false);
  const [open, setOpen] = useState<Source | null>(null);
  const [confirm, setConfirm] = useState<{ kind: 'archive' | 'restore'; it: KnowledgeItem } | null>(null);
  const [warning, setWarning] = useState(false);
  const q = useDeferredValue(search.trim());
  const m = useDeferredValue(machine.trim());

  const stats = useQuery({ queryKey: [...KEY, 'stats'], queryFn: knowledgeStats });
  const filter = { kind: archived ? 'E' as const : kind, machine: m || undefined, q: q.length >= 2 ? q : undefined, archived, sort };
  const list = useQuery({ queryKey: [...KEY, 'items', filter], queryFn: () => knowledgeItems(filter), placeholderData: (prev) => prev });
  const act = useMutation({
    mutationFn: ({ kind: k, it }: { kind: 'archive' | 'restore'; it: KnowledgeItem }) => (k === 'archive' ? archiveRecord(it.id) : restoreRecord(it.id)),
    onSuccess: (r) => {
      setConfirm(null);
      setWarning('warning' in r && !!r.warning);
      qc.invalidateQueries({ queryKey: KEY });
    },
  });
  const s = stats.data;
  const items = list.data?.items ?? [];

  return (
    <Page title={t('manage.knowledge.title')} subtitle={t('manage.knowledge.subtitle')}>
      <div className="flex h-full min-h-0 flex-col gap-4">
        <div className="grid grid-cols-4 gap-4">
          <Stat value={s?.records ?? '–'} label={t('manage.knowledge.stat.records')} note={s ? t('manage.knowledge.stat.recordsWeek', { count: s.records_week }) : undefined} />
          <Stat value={s?.manual_sections ?? '–'} label={t('manage.knowledge.stat.manual')} note={s ? t('manage.knowledge.stat.documents', { count: s.documents }) : undefined} />
          <Stat value={s?.history ?? '–'} label={t('manage.knowledge.stat.history')} note={t('manage.knowledge.stat.historyNote')} />
          <Stat value={s?.answered_rate_30d != null ? `${Math.round(s.answered_rate_30d * 100)}%` : '–'} label={t('manage.knowledge.stat.answered')}
            note={s ? t('manage.knowledge.stat.answeredNote', { answered: s.answered_30d, total: s.questions_30d }) : undefined} />
        </div>

        <div className="flex flex-wrap items-center gap-3">
          {!archived && (
            <Segmented label={t('manage.knowledge.kindLabel')} value={kind} onChange={setKind} options={[
              { value: 'all', label: t('manage.knowledge.kind.all') },
              { value: 'E', label: t('manage.knowledge.kind.E') },
              { value: 'M', label: t('manage.knowledge.kind.M') },
              { value: 'H', label: t('manage.knowledge.kind.H') },
            ]} />
          )}
          <input className={`${inputCls} !w-[130px] uppercase placeholder:normal-case`} value={machine} onChange={(e) => setMachine(e.target.value)} placeholder={t('manage.knowledge.machine')} aria-label={t('manage.knowledge.machine')} />
          <Search value={search} onChange={setSearch} placeholder={t('manage.knowledge.search')} />
          <div className="ml-auto flex items-center gap-3">
            <label className="flex items-center gap-2 text-sm">
              <span className="text-[var(--ink-muted)]">{t('manage.knowledge.sortLabel')}</span>
              <select className={`${inputCls} !w-auto`} value={sort} onChange={(e) => setSort(e.target.value as 'recent' | 'used')}>
                <option value="recent">{t('manage.knowledge.sort.recent')}</option>
                <option value="used">{t('manage.knowledge.sort.used')}</option>
              </select>
            </label>
            <Btn small kind={archived ? 'primary' : 'secondary'} aria-pressed={archived} onClick={() => setArchived((a) => !a)}>
              {t('manage.knowledge.showArchived')}{s?.records_archived ? ` (${s.records_archived})` : ''}
            </Btn>
          </div>
        </div>

        {warning && <Banner tone="safety" action={<Btn small kind="ghost" onClick={() => setWarning(false)}>{t('manage.common.close')}</Btn>}>{t('manage.knowledge.searchNotUpdated')}</Banner>}

        <div className="min-h-0 flex-1 overflow-y-auto">
          {list.isLoading ? <Spinner size={24} /> : list.isError ? <Banner tone="alert">{t('manage.errors.load')}</Banner> : !items.length ? (
            <Empty title={archived ? t('manage.knowledge.emptyArchived') : (q || m) ? t('manage.knowledge.noMatch') : t('manage.knowledge.empty')}>
              {!archived && !q && !m && <>
                {t('manage.knowledge.emptyHint')} <Link className="font-semibold text-[var(--green-deep)] underline" to="/manager/setup/documents">{t('manage.nav.documents')}</Link>
              </>}
            </Empty>
          ) : (
            <ul className="divide-y divide-[var(--line)] overflow-hidden rounded-[var(--radius-card,22px)] bg-[var(--white)]" aria-label={t('manage.knowledge.title')}>
              {items.map((it) => (
                <li key={`${it.kind}-${it.id}`} className="flex items-center gap-4 px-5 py-3.5">
                  <KindBadge kind={it.kind} />
                  <span className="sr-only">{t(`manage.knowledge.kind.${it.kind}`)}</span>
                  <div className="min-w-0 flex-1">
                    <button type="button" onClick={() => setOpen(toSource(it))} className="block max-w-full truncate text-left font-semibold hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--green)]">
                      {it.title}
                    </button>
                    <Meta it={it} />
                  </div>
                  {it.kind === 'M' && it.quality_notes && <Chip tone="safety">{t('manage.knowledge.checkPages')}</Chip>}
                  {it.status === 'archived' && <Chip>{t('manage.knowledge.archived')}</Chip>}
                  <div className="w-[120px] shrink-0 text-right text-sm">
                    {it.used > 0 ? <><b className="tabular-nums">{it.used}</b> <span className="text-[var(--ink-muted)]">{t('manage.knowledge.usedIn', { count: it.used })}</span></>
                      : <span className="text-[var(--ink-faint)]">{t('manage.knowledge.notUsed')}</span>}
                  </div>
                  <div className="w-[96px] shrink-0 text-right">
                    {it.kind === 'E' && (it.status === 'archived'
                      ? <Btn small kind="ghost" onClick={() => setConfirm({ kind: 'restore', it })}>{t('manage.knowledge.restore')}</Btn>
                      : <Btn small kind="ghost" className="!text-[var(--alert)]" onClick={() => setConfirm({ kind: 'archive', it })}>{t('manage.knowledge.archive')}</Btn>)}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      <SourceSheet source={open} onClose={() => setOpen(null)} />
      {confirm && (
        <Confirm open onClose={() => { setConfirm(null); act.reset(); }} busy={act.isPending} danger={confirm.kind === 'archive'}
          title={t(`manage.knowledge.confirm.${confirm.kind}.title`)} confirmLabel={t(`manage.knowledge.confirm.${confirm.kind}.cta`)}
          onConfirm={() => act.mutate(confirm)}
          body={<>
            <p className="font-semibold">{confirm.it.title}</p>
            <p className="mt-2">{t(`manage.knowledge.confirm.${confirm.kind}.body`, { count: confirm.it.used })}</p>
            {act.isError && <div className="mt-3"><Banner tone="alert">{errorMessage(act.error) ?? t('manage.errors.generic')}</Banner></div>}
          </>} />
      )}
    </Page>
  );
}
