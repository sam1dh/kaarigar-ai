/** 09 Questions for me (/tech/inbox): experts and supervisors see escalated questions. */
import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useNavigate } from 'react-router-dom';
import { Screen, Spinner, TopBar } from '../capture/ui';
import { expertCount, expertInbox, type Escalation } from './assistApi';
import { ago } from './parts';
import { useLiveRefresh } from './realtime';

/** Badge count for TechHome / bottom nav: questions assigned to me + unassigned ones. */
export function useInboxCount(enabled: boolean) {
  const q = useQuery({ queryKey: ['expert', 'count'], queryFn: expertCount, enabled, refetchInterval: 60_000 });
  useLiveRefresh('escalations', [['expert']], enabled);
  return (q.data?.mine ?? 0) + (q.data?.unassigned ?? 0);
}

function why(e: Escalation): string {
  if (e.answer_status === 'no_answer') return 'noAnswer';
  if (e.answer_status === 'failed') return 'failed';
  if (e.feedback === 'not_fixed') return 'notFixed';
  return 'asked';
}

export default function ExpertInbox() {
  const nav = useNavigate();
  const { t, i18n } = useTranslation();
  const [scope, setScope] = useState<'open' | 'done'>('open');
  const q = useQuery({ queryKey: ['expert', 'inbox', scope], queryFn: () => expertInbox(scope), refetchInterval: 60_000 });
  useLiveRefresh('escalations', [['expert']]);
  const items = q.data?.items ?? [];

  return (
    <Screen>
      <TopBar onBack={() => nav('/tech')} title={t('assist.inbox.title')} />
      <div role="tablist" className="mb-4 grid grid-cols-2 gap-1 rounded-full bg-[var(--surface)] p-1">
        {(['open', 'done'] as const).map((s) => (
          <button key={s} role="tab" aria-selected={scope === s} type="button" onClick={() => setScope(s)}
            className={`min-h-[44px] rounded-full text-sm font-semibold ${scope === s ? 'bg-[var(--green)] text-[var(--white)]' : 'text-[var(--ink-muted)]'}`}>
            {t(`assist.inbox.tab.${s}`)}
          </button>
        ))}
      </div>
      {q.isLoading && <Spinner size={22} />}
      {!q.isLoading && !items.length && (
        <p className="rounded-2xl bg-[var(--surface)] px-4 py-6 text-center text-[var(--ink-muted)]">{t(`assist.inbox.empty.${scope}`)}</p>
      )}
      <ul className="space-y-2">
        {items.map((e) => (
          <li key={e.id}>
            <Link to={`/tech/inbox/${e.id}`}
              className="block rounded-2xl bg-[var(--surface)] px-4 py-3 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--green)]">
              <div className="flex items-center justify-between gap-2 text-xs">
                <span className="text-[var(--ink-muted)]">
                  {e.machine && <b className="mr-2 text-[var(--green-deep)]" style={{ fontFamily: 'var(--font-heading)' }}>{e.machine.code}</b>}
                  {e.asked_by?.name} · {ago(e.created_at, i18n.language)}
                </span>
                {scope === 'open' && !e.assigned_to && (
                  <span className="rounded-full bg-[var(--safety-tint)] px-2.5 py-1 font-semibold">{t('assist.inbox.unassigned')}</span>
                )}
                {e.reply_in_progress && (
                  <span className="rounded-full bg-[var(--manual-tint)] px-2.5 py-1 font-semibold text-[var(--manual)]">{t('assist.inbox.draft')}</span>
                )}
              </div>
              <div className="mt-1 line-clamp-2 font-semibold leading-snug">{e.question.original ?? e.question.en}</div>
              <div className="mt-0.5 text-sm text-[var(--ink-muted)]">{t(`assist.inbox.why.${why(e)}`)}</div>
            </Link>
          </li>
        ))}
      </ul>
    </Screen>
  );
}
