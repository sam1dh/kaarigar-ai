/**
 * Shows a new PIN or temporary password ONCE. Kaarigar never stores it, so it lives only in this component's
 * state: closing the dialog forgets it. "Print slip" prints just the slip to hand to the person.
 */
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { Login } from '../manageApi';
import { Banner, Btn, Dialog, heading } from '../ui/kit';

export default function LoginSlip({ login, name, plantName, onClose }: { login: Login | null; name: string; plantName?: string; onClose: () => void }) {
  const { t } = useTranslation();
  const [copied, setCopied] = useState(false);
  if (!login) return null;
  const secret = login.method === 'pin' ? login.pin : login.temp_password;
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(secret);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch { /* clipboard blocked: they can read it off the screen */ }
  };
  return (
    <Dialog open onClose={onClose} title={t('manage.slip.title', { name })}
      footer={<>
        <Btn onClick={() => window.print()}>{t('manage.slip.print')}</Btn>
        <Btn kind="primary" onClick={onClose}>{t('manage.slip.done')}</Btn>
      </>}>
      <div className="space-y-4">
        <Banner tone="safety">{t('manage.slip.once')}</Banner>
        <div id="login-slip" className="rounded-2xl border-2 border-dashed border-[var(--line)] p-5">
          <p className="text-sm text-[var(--ink-muted)]">{plantName ?? 'Kaarigar AI'}</p>
          <p className="mt-0.5 text-lg font-semibold" style={heading}>{name}</p>
          <dl className="mt-4 grid grid-cols-[auto_1fr] items-baseline gap-x-6 gap-y-3">
            {login.method === 'pin' ? (
              <>
                {login.plant_code && <><dt className="text-sm text-[var(--ink-muted)]">{t('manage.slip.plant')}</dt><dd className="font-semibold">{login.plant_code}</dd></>}
                <dt className="text-sm text-[var(--ink-muted)]">{t('manage.slip.employeeId')}</dt><dd className="font-semibold">{login.employee_id}</dd>
                <dt className="text-sm text-[var(--ink-muted)]">PIN</dt>
                <dd className="text-[40px] font-semibold leading-none tracking-[0.25em] tabular-nums" style={heading} aria-label={secret.split('').join(' ')}>{secret}</dd>
              </>
            ) : (
              <>
                <dt className="text-sm text-[var(--ink-muted)]">{t('manage.slip.email')}</dt><dd className="font-semibold break-all">{login.email}</dd>
                <dt className="text-sm text-[var(--ink-muted)]">{t('manage.slip.tempPassword')}</dt>
                <dd className="text-[26px] font-semibold tracking-wider" style={{ fontFamily: 'var(--font-body)' }}>{secret}</dd>
              </>
            )}
          </dl>
          <p className="mt-4 text-sm text-[var(--ink-muted)]">{login.method === 'pin' ? t('manage.slip.howPin') : t('manage.slip.howEmail')}</p>
        </div>
        <Btn small kind="ghost" onClick={copy}>{copied ? t('manage.slip.copied') : t('manage.slip.copy')}</Btn>
      </div>
      <style>{`@media print { body * { visibility: hidden !important; } #login-slip, #login-slip * { visibility: visible !important; } #login-slip { position: fixed; left: 24px; top: 24px; width: 90mm; } }`}</style>
    </Dialog>
  );
}
