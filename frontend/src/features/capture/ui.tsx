/** Small shared pieces for Phase 2 screens (phone and web). Uses the Phase 0 CSS variables. */
import { useTranslation } from 'react-i18next';
import type { ButtonHTMLAttributes, ReactNode } from 'react';
import type { CaptureRecord, Issue } from './captureApi';

export function Screen({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-[100dvh] bg-[var(--bg-enamel)] text-[var(--ink)]" style={{ fontFamily: 'var(--font-body)' }}>
      <div className="mx-auto flex min-h-[100dvh] max-w-[480px] flex-col px-4 pb-6 pt-3">{children}</div>
    </div>
  );
}

export function TopBar({ title, onBack, right }: { title: ReactNode; onBack?: () => void; right?: ReactNode }) {
  const { t } = useTranslation();
  return (
    <div className="mb-3 flex items-center gap-3">
      {onBack && (
        <button type="button" onClick={onBack} aria-label={t('capture.back')}
          className="grid h-11 w-11 place-items-center rounded-full bg-[var(--surface)] text-[var(--ink)] focus-visible:ring-2 focus-visible:ring-[var(--green)]">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"
            strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M15 18l-6-6 6-6" /></svg>
        </button>
      )}
      <div className="min-w-0 flex-1 text-lg font-semibold leading-tight" style={{ fontFamily: 'var(--font-heading)' }}>
        {title}
      </div>
      {right}
    </div>
  );
}

export function MachineChip({ code, name }: { code: string; name?: string | null }) {
  return (
    <span className="inline-flex items-center gap-2 rounded-full bg-[var(--surface)] px-3 py-1 text-sm">
      <b className="text-[var(--green-deep)]" style={{ fontFamily: 'var(--font-heading)' }}>{code}</b>
      {name && <span className="text-[var(--ink-muted)]">{name}</span>}
    </span>
  );
}

type BtnKind = 'primary' | 'secondary' | 'quiet' | 'danger';
export function BigButton({ kind = 'primary', children, className = '', ...rest }:
  { kind?: BtnKind } & ButtonHTMLAttributes<HTMLButtonElement>) {
  const styles: Record<BtnKind, string> = {
    primary: 'bg-[var(--green)] text-white',
    secondary: 'bg-[var(--surface)] text-[var(--ink)] border border-[var(--line)]',
    quiet: 'bg-transparent text-[var(--ink-muted)] underline-offset-4 hover:underline',
    danger: 'bg-[var(--alert)] text-white',
  };
  return (
    <button type="button" {...rest}
      className={`min-h-[60px] w-full rounded-[var(--radius-button,18px)] px-5 text-base font-semibold leading-snug transition-opacity disabled:opacity-50 focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-[var(--green-tint)] ${styles[kind]} ${className}`}>
      {children}
    </button>
  );
}

export function Card({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <div className={`rounded-[var(--radius-card,22px)] bg-[var(--surface)] p-4 ${className}`}>{children}</div>;
}

/** Status pill used in "My notes" and the review list. */
export function StatusPill({ rec }: { rec: Pick<CaptureRecord, 'status' | 'stage' | 'processing'> }) {
  const { t } = useTranslation();
  let key = rec.status as string;
  if (rec.processing) key = 'processing';
  else if (rec.stage === 'failed') key = 'failed';
  const tone: Record<string, string> = {
    processing: 'bg-[var(--green-tint)] text-[var(--green-deep)]',
    expert_review: 'bg-[var(--safety-tint)] text-[var(--ink)]',
    pending: 'bg-[var(--manual-tint)] text-[var(--manual)]',
    approved: 'bg-[var(--green-tint)] text-[var(--green-deep)]',
    rejected: 'bg-[var(--alert-tint)] text-[var(--alert)]',
    failed: 'bg-[var(--alert-tint)] text-[var(--alert)]',
    draft: 'bg-[var(--surface)] text-[var(--ink-muted)]',
  };
  return (
    <span className={`inline-flex shrink-0 items-center rounded-full px-2.5 py-1 text-xs font-semibold ${tone[key] ?? tone.draft}`}>
      {t(`capture.status.${key}`)}
    </span>
  );
}

/** AI check messages. `messages` lets the phone show translated text; order matches `issues`. */
export function IssueList({ issues, safetyOk, messages }: { issues: Issue[]; safetyOk: boolean | null | undefined; messages?: string[] }) {
  const { t } = useTranslation();
  const showSafety = safetyOk === false && !issues.some((i) => i.field === 'safety_note');
  if (!issues.length && !showSafety) {
    return (
      <div className="flex items-center gap-2 rounded-2xl bg-[var(--green-tint)] px-4 py-3 text-sm text-[var(--green-deep)]">
        <CheckIcon /> {t('capture.check.allGood')}
      </div>
    );
  }
  return (
    <ul className="space-y-2" aria-label={t('capture.check.title')}>
      {showSafety && (
        <li className="flex gap-3 rounded-2xl border border-[var(--safety)] bg-[var(--safety-tint)] px-4 py-3 text-sm">
          <ShieldIcon /> <span>{t('capture.check.safetyMissing')}</span>
        </li>
      )}
      {issues.map((iss, i) => {
        const safety = iss.field === 'safety_note';
        const tone = safety
          ? 'border-[var(--safety)] bg-[var(--safety-tint)]'
          : iss.severity === 'high'
            ? 'border-[var(--alert)] bg-[var(--alert-tint)]'
            : 'border-[var(--line)] bg-[var(--white)]';
        return (
          <li key={i} className={`flex gap-3 rounded-2xl border px-4 py-3 text-sm ${tone}`}>
            {safety ? <ShieldIcon /> : <AlertIcon high={iss.severity === 'high'} />}
            <span>
              <b className="mr-1">{t(`capture.fields.${iss.field}`, { defaultValue: '' })}</b>
              {messages?.[i] ?? iss.message}
            </span>
          </li>
        );
      })}
    </ul>
  );
}

export function Spinner({ size = 18 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" className="motion-safe:animate-spin" aria-hidden="true">
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeOpacity="0.25" strokeWidth="3" fill="none" />
      <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="3" fill="none" strokeLinecap="round" />
    </svg>
  );
}

export const CheckIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.6"
    strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5" /></svg>
);
export const ShieldIcon = () => (
  <svg className="mt-0.5 shrink-0" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--ink)" strokeWidth="2"
    strokeLinejoin="round" aria-hidden="true"><path d="M12 3l8 3v6c0 4.5-3.4 8.3-8 9-4.6-.7-8-4.5-8-9V6l8-3z" /><path d="M12 8v5M12 16h.01" strokeLinecap="round" /></svg>
);
export const AlertIcon = ({ high }: { high?: boolean }) => (
  <svg className="mt-0.5 shrink-0" width="18" height="18" viewBox="0 0 24 24" fill="none"
    stroke={high ? 'var(--alert)' : 'var(--ink-muted)'} strokeWidth="2" strokeLinecap="round" aria-hidden="true">
    <circle cx="12" cy="12" r="9" /><path d="M12 7.5v5.5M12 16.5h.01" /></svg>
);
