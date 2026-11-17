/** 08 Sent (/tech/records/:id/sent) */
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { useNavigate, useParams } from 'react-router-dom';
import { getRecord } from './captureApi';
import { BigButton, CheckIcon, Screen } from './ui';

export default function SentScreen() {
  const { id = '' } = useParams();
  const nav = useNavigate();
  const { t } = useTranslation();
  const q = useQuery({ queryKey: ['capture', 'record', id], queryFn: () => getRecord(id) });
  const code = q.data?.machine.code;

  return (
    <Screen>
      <div className="flex flex-1 flex-col items-center justify-center text-center">
        <div className="mb-6 grid h-24 w-24 place-items-center rounded-full bg-[var(--green)] text-white [&>svg]:h-12 [&>svg]:w-12">
          <CheckIcon />
        </div>
        <h1 className="mb-2 text-2xl font-bold" style={{ fontFamily: 'var(--font-heading)' }}>{t('capture.sent.title')}</h1>
        <p className="max-w-[320px] text-[var(--ink-muted)]">{t('capture.sent.next')}</p>
        {q.data?.fields.symptom && (
          <p className="mt-5 rounded-2xl bg-[var(--surface)] px-4 py-3 text-sm">
            <b style={{ fontFamily: 'var(--font-heading)' }}>{code}</b> · {q.data.fields_local?.symptom ?? q.data.fields.symptom}
          </p>
        )}
      </div>
      <div className="space-y-3">
        {code && <BigButton onClick={() => nav(`/tech/machines/${encodeURIComponent(code)}/record`)}>{t('capture.sent.another')}</BigButton>}
        <BigButton kind="secondary" onClick={() => nav(code ? `/tech/machines/${encodeURIComponent(code)}` : '/tech')}>
          {t('capture.sent.backToMachine')}
        </BigButton>
      </div>
    </Screen>
  );
}
