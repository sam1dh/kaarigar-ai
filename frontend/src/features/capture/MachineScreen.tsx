/**
 * 02 Machine (/tech/machines/:code) — minimal version for Phase 2.
 * "Ask a question" arrives in Phase 3. "Record a repair" is shown to experts and supervisors only.
 */
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { useNavigate, useParams } from 'react-router-dom';
import { getMe } from './captureApi';
import MyNotes from './MyNotes';
import { BigButton, Card, Screen, TopBar } from './ui';

export default function MachineScreen() {
  const { code = '' } = useParams();
  const nav = useNavigate();
  const { t } = useTranslation();
  const me = useQuery({ queryKey: ['auth', 'me'], queryFn: getMe, staleTime: 5 * 60_000 });
  const canRecord = me.data?.role === 'expert' || me.data?.role === 'supervisor';

  return (
    <Screen>
      <TopBar onBack={() => nav('/tech')} title={<span style={{ fontFamily: 'var(--font-heading)' }}>{code}</span>} />
      <Card className="mb-4">
        <div className="text-sm text-[var(--ink-muted)]">{t('capture.machine.subtitle')}</div>
        <div className="mt-1 text-3xl font-bold text-[var(--green-deep)]" style={{ fontFamily: 'var(--font-heading)' }}>
          {code}
        </div>
      </Card>

      <div className="space-y-3">
        <BigButton kind="secondary" disabled title={t('capture.machine.askSoon')}>
          {t('capture.machine.ask')} <span className="ml-1 text-xs font-normal">({t('capture.machine.askSoon')})</span>
        </BigButton>
        {canRecord && (
          <BigButton onClick={() => nav(`/tech/machines/${encodeURIComponent(code)}/record`)}>
            {t('capture.machine.record')}
          </BigButton>
        )}
      </div>

      {canRecord && (
        <section className="mt-6">
          <h2 className="mb-2 text-sm font-semibold text-[var(--ink-muted)]">{t('capture.myNotes.onThisMachine')}</h2>
          <MyNotes machineCode={code} limit={5} />
        </section>
      )}
    </Screen>
  );
}
