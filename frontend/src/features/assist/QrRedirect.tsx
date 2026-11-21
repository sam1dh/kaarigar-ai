/**
 * /m/:token — what a machine's QR sticker opens (Phase 4 prints https://app.kaarigar-ai.online/m/<qr_token>).
 * Signed in: goes to that machine's screen. Not signed in: the Phase 0 guard sends the person to login first
 * (keep this route inside the technician guard so it returns here after login).
 */
import { useQuery } from '@tanstack/react-query';
import { useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate, useParams } from 'react-router-dom';
import { BigButton, Screen, Spinner } from '../capture/ui';
import { machineByQr } from './assistApi';
import { Notice } from './parts';

export default function QrRedirect() {
  const { token = '' } = useParams();
  const nav = useNavigate();
  const { t } = useTranslation();
  const q = useQuery({ queryKey: ['assist', 'qr', token], queryFn: () => machineByQr(token), retry: false });

  useEffect(() => {
    if (q.data?.code) nav(`/tech/machines/${encodeURIComponent(q.data.code)}`, { replace: true });
  }, [q.data, nav]);

  return (
    <Screen>
      <div className="flex flex-1 flex-col items-center justify-center gap-4 text-center">
        {q.isLoading && <><Spinner size={28} /><p className="text-[var(--ink-muted)]">{t('assist.qr.opening')}</p></>}
        {q.isError && (
          <>
            <Notice tone="alert">{t('assist.qr.unknown')}</Notice>
            <BigButton kind="secondary" onClick={() => nav('/tech', { replace: true })}>{t('assist.qr.home')}</BigButton>
          </>
        )}
      </div>
    </Screen>
  );
}
