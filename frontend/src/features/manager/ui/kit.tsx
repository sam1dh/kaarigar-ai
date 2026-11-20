/**
 * Small UI kit for the manager screens (W3–W8). Same tokens as W1/W2: enamel background, white cards,
 * deep green actions, Anek headings, IBM Plex body. No new dependencies.
 */
import { useEffect, useId, useRef, type ButtonHTMLAttributes, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Spinner } from '../../capture/ui';

export { Spinner };

export const heading = { fontFamily: 'var(--font-heading)' } as const;

export function Page({ title, subtitle, actions, children }: { title: ReactNode; subtitle?: ReactNode; actions?: ReactNode; children: ReactNode }) {
  return (
    <div className="flex h-full min-h-0 flex-col" style={{ fontFamily: 'var(--font-body)' }}>
      <div className="mb-5 flex flex-wrap items-end justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-[32px] font-semibold leading-tight" style={heading}>{title}</h1>
          {subtitle && <p className="mt-0.5 text-[var(--ink-muted)]">{subtitle}</p>}
        </div>
        {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
      </div>
      <div className="min-h-0 flex-1">{children}</div>
    </div>
  );
}

type BtnKind = 'primary' | 'secondary' | 'ghost' | 'danger';
const BTN: Record<BtnKind, string> = {
  primary: 'bg-[var(--green)] text-[var(--white)] hover:bg-[var(--green-deep)] disabled:bg-[var(--ink-faint)]',
  secondary: 'border border-[var(--line)] bg-[var(--white)] text-[var(--ink)] hover:border-[var(--green)] disabled:text-[var(--ink-faint)]',
  ghost: 'text-[var(--green-deep)] hover:bg-[var(--green-tint)] disabled:text-[var(--ink-faint)]',
  danger: 'border border-[var(--alert)] bg-[var(--white)] text-[var(--alert)] hover:bg-[var(--alert-tint)] disabled:opacity-50',
};
export function Btn({ kind = 'secondary', busy, small, className = '', children, ...rest }:
  ButtonHTMLAttributes<HTMLButtonElement> & { kind?: BtnKind; busy?: boolean; small?: boolean }) {
  return (
    <button type="button" {...rest} disabled={rest.disabled || busy}
      className={`inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-xl font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--green)] focus-visible:ring-offset-2 disabled:cursor-not-allowed ${small ? 'min-h-[34px] px-3 text-sm' : 'min-h-[42px] px-4'} ${BTN[kind]} ${className}`}>
      {busy && <Spinner size={16} />}
      {children}
    </button>
  );
}

export function Segmented<T extends string | number>({ label, options, value, onChange }:
  { label: string; options: { value: T; label: ReactNode; count?: number }[]; value: T; onChange: (v: T) => void }) {
  return (
    <div role="tablist" aria-label={label} className="flex gap-1 rounded-xl border border-[var(--line)] bg-[var(--white)] p-1">
      {options.map((o) => (
        <button key={String(o.value)} type="button" role="tab" aria-selected={value === o.value} onClick={() => onChange(o.value)}
          className={`min-h-[36px] rounded-lg px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--green)] ${value === o.value ? 'bg-[var(--green)] font-semibold text-[var(--white)]' : 'text-[var(--ink)] hover:bg-[var(--surface)]'}`}>
          {o.label}
          {o.count !== undefined && <span className={`ml-1.5 tabular-nums ${value === o.value ? 'opacity-80' : 'text-[var(--ink-faint)]'}`}>{o.count}</span>}
        </button>
      ))}
    </div>
  );
}

type Tone = 'green' | 'manual' | 'history' | 'safety' | 'alert' | 'plain';
const CHIP: Record<Tone, string> = {
  green: 'bg-[var(--green-tint)] text-[var(--green-deep)]',
  manual: 'bg-[var(--manual-tint)] text-[var(--manual)]',
  history: 'bg-[var(--history-tint)] text-[var(--history)]',
  safety: 'bg-[var(--safety-tint)] text-[var(--ink)]',
  alert: 'bg-[var(--alert-tint)] text-[var(--alert)]',
  plain: 'border border-[var(--line)] bg-[var(--surface)] text-[var(--ink-muted)]',
};
export function Chip({ tone = 'plain', children }: { tone?: Tone; children: ReactNode }) {
  return <span className={`inline-flex shrink-0 items-center gap-1 whitespace-nowrap rounded-full px-2.5 py-0.5 text-xs font-semibold ${CHIP[tone]}`}>{children}</span>;
}

export function Field({ label, hint, error, children }: { label: ReactNode; hint?: ReactNode; error?: ReactNode; children: (id: string, describedBy?: string) => ReactNode }) {
  const id = useId();
  const hintId = hint || error ? `${id}-hint` : undefined;
  return (
    <div className="space-y-1">
      <label htmlFor={id} className="block text-sm font-semibold">{label}</label>
      {children(id, hintId)}
      {(error || hint) && <p id={hintId} className={`text-xs ${error ? 'text-[var(--alert)]' : 'text-[var(--ink-muted)]'}`}>{error ?? hint}</p>}
    </div>
  );
}
export const inputCls = 'w-full min-h-[42px] rounded-xl border border-[var(--line)] bg-[var(--white)] px-3 text-[15px] focus:border-[var(--green)] focus:outline-none focus:ring-2 focus:ring-[var(--green-tint)] disabled:bg-[var(--surface)]';

export function Card({ className = '', children }: { className?: string; children: ReactNode }) {
  return <section className={`rounded-[var(--radius-card,22px)] bg-[var(--white)] ${className}`}>{children}</section>;
}

export function Empty({ title, children }: { title: ReactNode; children?: ReactNode }) {
  return (
    <div className="rounded-[var(--radius-card,22px)] bg-[var(--surface)] p-8">
      <p className="font-semibold">{title}</p>
      {children && <div className="mt-1 text-[var(--ink-muted)]">{children}</div>}
    </div>
  );
}

export function Banner({ tone = 'info', children, action }: { tone?: 'info' | 'alert' | 'ok' | 'safety'; children: ReactNode; action?: ReactNode }) {
  const cls = tone === 'alert' ? 'bg-[var(--alert-tint)] text-[var(--alert)]' : tone === 'ok' ? 'bg-[var(--green-tint)] text-[var(--green-deep)]'
    : tone === 'safety' ? 'bg-[var(--safety-tint)] text-[var(--ink)]' : 'bg-[var(--surface)] text-[var(--ink)] border border-[var(--line)]';
  return (
    <div role={tone === 'alert' ? 'alert' : 'status'} className={`flex flex-wrap items-center gap-3 rounded-2xl px-4 py-3 text-sm ${cls}`}>
      <div className="min-w-0 flex-1">{children}</div>
      {action}
    </div>
  );
}

/** Centered dialog. Escape and the backdrop close it; focus moves into it and back when it closes. */
export function Dialog({ open, onClose, title, children, footer, wide }:
  { open: boolean; onClose: () => void; title: ReactNode; children: ReactNode; footer?: ReactNode; wide?: boolean }) {
  const { t } = useTranslation();
  const ref = useRef<HTMLDivElement>(null);
  const titleId = useId();
  useEffect(() => {
    if (!open) return;
    const before = document.activeElement as HTMLElement | null;
    const first = ref.current?.querySelector<HTMLElement>('input, select, textarea, button:not([data-close])');
    (first ?? ref.current)?.focus();
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', onKey);
    return () => { document.removeEventListener('keydown', onKey); before?.focus?.(); };
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-[rgba(28,38,38,0.45)] p-4" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div ref={ref} role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1}
        className={`flex max-h-[90vh] w-full flex-col rounded-[22px] bg-[var(--white)] shadow-[0_12px_40px_rgba(28,38,38,0.18)] ${wide ? 'max-w-[760px]' : 'max-w-[480px]'}`}
        style={{ fontFamily: 'var(--font-body)' }}>
        <div className="flex items-start justify-between gap-4 px-6 pt-5">
          <h2 id={titleId} className="text-xl font-semibold" style={heading}>{title}</h2>
          <button type="button" data-close onClick={onClose} aria-label={t('manage.common.close')}
            className="-mr-2 grid h-9 w-9 place-items-center rounded-lg text-[var(--ink-muted)] hover:bg-[var(--surface)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--green)]">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" aria-hidden><path d="M6 6l12 12M18 6L6 18" /></svg>
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-4">{children}</div>
        {footer && <div className="flex flex-wrap justify-end gap-2 border-t border-[var(--line)] px-6 py-4">{footer}</div>}
      </div>
    </div>
  );
}

export function Confirm({ open, onClose, title, body, confirmLabel, danger, busy, onConfirm }:
  { open: boolean; onClose: () => void; title: ReactNode; body: ReactNode; confirmLabel: ReactNode; danger?: boolean; busy?: boolean; onConfirm: () => void }) {
  const { t } = useTranslation();
  return (
    <Dialog open={open} onClose={onClose} title={title}
      footer={<><Btn onClick={onClose}>{t('manage.common.cancel')}</Btn><Btn kind={danger ? 'danger' : 'primary'} busy={busy} onClick={onConfirm}>{confirmLabel}</Btn></>}>
      <div className="leading-relaxed text-[var(--ink)]">{body}</div>
    </Dialog>
  );
}

export function dateFmt(iso: string | null | undefined, lang: string, withYear = true) {
  if (!iso) return '';
  return new Date(iso).toLocaleDateString(lang, { day: 'numeric', month: 'short', ...(withYear ? { year: 'numeric' } : {}) });
}

export function Search({ value, onChange, placeholder }: { value: string; onChange: (v: string) => void; placeholder: string }) {
  return (
    <div className="relative">
      <svg className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[var(--ink-faint)]" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" aria-hidden><circle cx="11" cy="11" r="7" /><path d="M20 20l-3.5-3.5" strokeLinecap="round" /></svg>
      <input type="search" value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} aria-label={placeholder}
        className={`${inputCls} !w-[280px] pl-9`} />
    </div>
  );
}
