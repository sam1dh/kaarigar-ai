/**
 * W1 Review queue (/manager). Replaces the Phase 0 empty state inside ManagerLayout.
 * Left: records waiting for approval (oldest first). Right: the selected record.
 */
import { useQuery } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { getReviewQueue, type QueueItem } from '../../capture/captureApi';
import { AlertIcon, ShieldIcon, Spinner } from '../../capture/ui';
import RecordReview from './RecordReview';

function ago(iso: string | null, lang: string) {
  if (!iso) return '';
  const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  const rtf = new Intl.RelativeTimeFormat(lang, { numeric: 'auto' });
  if (mins < 60) return rtf.format(-mins, 'minute');
  if (mins < 60 * 24) return rtf.format(-Math.round(mins / 60), 'hour');
  return rtf.format(-Math.round(mins / 1440), 'day');
}

export default function ReviewQueue() {
  const { t, i18n } = useTranslation();
  const q = useQuery({ queryKey: ['review', 'queue'], queryFn: getReviewQueue, refetchInterval: 20000 });
  const items = q.data?.items ?? [];
  const [selected, setSelected] = useState<string | null>(null);

  useEffect(() => {
    if (!items.length) setSelected(null);
    else if (!selected || !items.some((i) => i.id === selected)) setSelected(items[0].id);
  }, [items, selected]);

  const nextAfter = (id: string) => {
    const idx = items.findIndex((i) => i.id === id);
    const rest = items.filter((i) => i.id !== id);
    setSelected(rest.length ? rest[Math.min(idx, rest.length - 1)].id : null);
  };

  return (
    <div className="flex h-full min-h-0 flex-col" style={{ fontFamily: 'var(--font-body)' }}>
      <div className="mb-4 flex items-baseline gap-3">
        <h1 className="text-2xl font-bold" style={{ fontFamily: 'var(--font-heading)' }}>{t('review.title')}</h1>
        {!!q.data?.count && <span className="text-[var(--ink-muted)]">{t('review.waiting', { count: q.data.count })}</span>}
      </div>

      {q.isLoading ? (
        <div className="text-[var(--ink-muted)]"><Spinner size={24} /></div>
      ) : !items.length ? (
        <div className="rounded-[var(--radius-card,22px)] bg-[var(--surface)] p-8 text-[var(--ink-muted)]">{t('review.empty')}</div>
      ) : (
        <div className="grid min-h-0 flex-1 grid-cols-[minmax(280px,360px)_1fr] gap-5">
          <ul className="min-h-0 space-y-2 overflow-y-auto pr-1" aria-label={t('review.title')}>
            {items.map((it: QueueItem) => (
              <li key={it.id}>
                <button type="button" onClick={() => setSelected(it.id)} aria-current={selected === it.id}
                  className={`w-full rounded-2xl border px-4 py-3 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--green)] ${selected === it.id ? 'border-[var(--green)] bg-[var(--white)]' : 'border-transparent bg-[var(--surface)] hover:border-[var(--line)]'}`}>
                  <div className="flex items-center justify-between gap-2">
                    <b className="text-[var(--green-deep)]" style={{ fontFamily: 'var(--font-heading)' }}>{it.machine.code}</b>
                    <span className="text-xs text-[var(--ink-faint)]">{ago(it.submitted_at, i18n.language)}</span>
                  </div>
                  <div className={`mt-1 line-clamp-2 font-semibold ${it.symptom ? '' : 'italic text-[var(--ink-faint)]'}`}>
                    {it.symptom || t('review.noProblemStated')}
                  </div>
                  <div className="mt-1 flex items-center gap-3 text-xs text-[var(--ink-muted)]">
                    <span>{it.author.name}</span>
                    {it.issues_high > 0 && <span className="inline-flex items-center gap-1 text-[var(--alert)]"><AlertIcon high /> {it.issues_high}</span>}
                    {it.safety_ok === false && <span className="inline-flex items-center gap-1"><ShieldIcon /> {t('review.safety')}</span>}
                  </div>
                </button>
              </li>
            ))}
          </ul>
          <div className="min-h-0 overflow-hidden">
            {selected && <RecordReview key={selected} id={selected} onDone={() => nextAfter(selected)} />}
          </div>
        </div>
      )}
    </div>
  );
}
