/** "My questions" (/tech/questions) and a short version for TechHome. */
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Link, useNavigate } from 'react-router-dom';
import { Screen, Spinner, TopBar } from '../capture/ui';
import { listQueries, type QueryListItem } from './assistApi';
import { ago } from './parts';
import { useLiveRefresh } from './realtime';

function pill(q: QueryListItem): { key: string; cls: string } {
  if (q.escalation?.status === 'answered') return { key: 'replied', cls: 'bg-[var(--green)] text-[var(--white)]' };
  if (q.escalation?.status === 'open') return { key: 'withExpert', cls: 'bg-[var(--safety-tint)] text-[var(--ink)]' };
  if (q.feedback === 'fixed') return { key: 'fixed', cls: 'bg-[var(--green-tint)] text-[var(--green-deep)]' };
  if (q.status === 'answered') return { key: 'answered', cls: 'bg-[var(--surface)] text-[var(--ink-muted)] border border-[var(--line)]' };
  if (q.status === 'answering') return { key: 'answering', cls: 'bg-[var(--surface)] text-[var(--ink-muted)]' };
  return { key: 'noAnswer', cls: 'bg-[var(--alert-tint)] text-[var(--alert)]' };
}

export function MyQuestionsList({ limit = 20 }: { limit?: number }) {
  const { t, i18n } = useTranslation();
  const q = useQuery({ queryKey: ['assist', 'queries', limit], queryFn: () => listQueries(limit), refetchInterval: 60_000 });
  useLiveRefresh('escalations', [['assist', 'queries']]);
  if (q.isLoading) return <div className="py-4 text-[var(--ink-muted)]"><Spinner /></div>;
  const items = q.data?.items ?? [];
  if (!items.length) return <p className="rounded-2xl bg-[var(--surface)] px-4 py-3 text-sm text-[var(--ink-muted)]">{t('assist.mine.empty')}</p>;
  return (
    <ul className="space-y-2">
      {items.map((it) => {
        const p = pill(it);
        return (
          <li key={it.id}>
            <Link to={`/tech/questions/${it.id}`}
              className="block rounded-2xl bg-[var(--surface)] px-4 py-3 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--green)]">
              <div className="flex items-center justify-between gap-2 text-xs text-[var(--ink-faint)]">
                <span>{it.machine && <b className="mr-2 text-[var(--green-deep)]" style={{ fontFamily: 'var(--font-heading)' }}>{it.machine.code}</b>}{ago(it.created_at, i18n.language)}</span>
                <span className={`inline-flex shrink-0 items-center rounded-full px-2.5 py-1 text-xs font-semibold ${p.cls}`}>{t(`assist.mine.status.${p.key}`)}</span>
              </div>
              <div className="mt-1 line-clamp-2 font-semibold leading-snug">{it.question.original ?? it.question.en ?? '…'}</div>
              {it.first_step && <div className="mt-0.5 line-clamp-1 text-sm text-[var(--ink-muted)]">{it.first_step}</div>}
            </Link>
          </li>
        );
      })}
    </ul>
  );
}

export default function MyQuestions() {
  const nav = useNavigate();
  const { t } = useTranslation();
  return (
    <Screen>
      <TopBar onBack={() => nav('/tech')} title={t('assist.mine.title')} />
      <MyQuestionsList limit={30} />
    </Screen>
  );
}
