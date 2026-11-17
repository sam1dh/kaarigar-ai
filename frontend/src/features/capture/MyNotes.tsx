/** "My notes": the expert's recent recordings with their status. Use on TechHome (experts) and MachineScreen. */
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { listMyRecords } from './captureApi';
import { StatusPill } from './ui';

export default function MyNotes({ machineCode, limit = 5 }: { machineCode?: string; limit?: number }) {
  const { t, i18n } = useTranslation();
  const q = useQuery({
    queryKey: ['capture', 'mine', machineCode ?? 'all', limit],
    queryFn: () => listMyRecords(machineCode, limit),
    refetchInterval: (query) => (query.state.data?.items.some((r) => r.processing || r.status === 'pending') ? 15000 : false),
  });

  if (q.isLoading) return null;
  const items = q.data?.items ?? [];
  if (!items.length) return <p className="text-sm text-[var(--ink-faint)]">{t('capture.myNotes.empty')}</p>;

  return (
    <ul className="space-y-2">
      {items.map((r) => (
        <li key={r.id}>
          <Link to={`/tech/records/${r.id}`}
            className="flex items-center gap-3 rounded-2xl bg-[var(--surface)] px-4 py-3 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--green)]">
            <div className="min-w-0 flex-1">
              <div className="truncate font-semibold">
                <span className="mr-2 text-[var(--green-deep)]" style={{ fontFamily: 'var(--font-heading)' }}>{r.machine.code}</span>
                {r.fields_local?.symptom ?? r.fields.symptom ?? t('capture.myNotes.untitled')}
              </div>
              <div className="text-xs text-[var(--ink-muted)]">
                {new Date(r.created_at).toLocaleDateString(i18n.language, { day: 'numeric', month: 'short' })}
                {r.status === 'rejected' && r.reject_reason ? ` · ${r.reject_reason}` : ''}
              </div>
            </div>
            <StatusPill rec={r} />
          </Link>
        </li>
      ))}
    </ul>
  );
}
