/**
 * Editable record fields, shared by the phone check screen (07) and the supervisor review (W1).
 * Shows `display` values (translated on the phone) and reports only the keys the user changed.
 */
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { FieldEdits, Part } from './captureApi';

export interface DisplayFields {
  symptom: string | null;
  cause: string | null;
  fix: string | null;
  steps: string[];
  safety_note: string | null;
  parts?: Part[] | null;
  tools?: string[] | null;
  downtime_min?: number | null;
}

interface Props {
  display: DisplayFields;
  missing?: string[] | null;
  editable: boolean;
  onChange: (edits: FieldEdits) => void;   // only changed keys
  compact?: boolean;                       // web layout
  emptyPlaceholder?: string;               // placeholder for the text areas
}

type TextKey = 'symptom' | 'cause' | 'fix' | 'safety_note';
const TEXT_KEYS: TextKey[] = ['symptom', 'cause', 'fix'];

export default function FieldEditor({ display, missing, editable, onChange, compact, emptyPlaceholder }: Props) {
  const { t } = useTranslation();
  const [vals, setVals] = useState<DisplayFields>(display);
  const [dirty, setDirty] = useState<Set<string>>(new Set());

  useEffect(() => { setVals(display); setDirty(new Set()); }, [display]);

  const emit = (next: DisplayFields, nextDirty: Set<string>) => {
    const edits: FieldEdits = {};
    nextDirty.forEach((k) => {
      if (k === 'steps') edits.steps = next.steps.map((s) => s.trim()).filter(Boolean);
      else if (k === 'downtime_min') edits.downtime_min = next.downtime_min ?? null;
      else (edits as Record<string, unknown>)[k] = ((next as any)[k] ?? '').trim() || null;
    });
    onChange(edits);
  };

  const set = (k: keyof DisplayFields, v: unknown) => {
    const next = { ...vals, [k]: v } as DisplayFields;
    const nd = new Set(dirty).add(k);
    setVals(next);
    setDirty(nd);
    emit(next, nd);
  };

  const isMissing = (k: string) => (missing ?? []).includes(k);
  const box = 'w-full resize-none rounded-xl border border-[var(--line)] bg-[var(--white)] px-3 py-2 text-base focus:border-[var(--green)] focus:outline-none focus:ring-2 focus:ring-[var(--green-tint)]';

  const textField = (k: TextKey, rows = 2) => (
    <div key={k} className={`rounded-2xl bg-[var(--surface)] p-3 ${compact ? '' : 'mb-3'}`}>
      <label htmlFor={`f-${k}`} className="mb-1 flex items-center justify-between text-sm font-semibold">
        <span>{t(`capture.fields.${k}`)}</span>
        {isMissing(k) && !vals[k] && <span className="text-xs font-normal text-[var(--alert)]">{t('capture.fields.notSaid')}</span>}
        {dirty.has(k) && <span className="text-xs font-normal text-[var(--green)]">{t('capture.fields.edited')}</span>}
      </label>
      {editable ? (
        <textarea id={`f-${k}`} rows={rows} className={box} value={vals[k] ?? ''}
          placeholder={emptyPlaceholder ?? t('capture.fields.placeholder')} onChange={(e) => set(k, e.target.value)} />
      ) : (
        <p className="whitespace-pre-wrap">{vals[k] || '—'}</p>
      )}
    </div>
  );

  return (
    <div className={compact ? 'grid gap-3' : ''}>
      {compact ? (
        <>
          <div className="grid gap-3 md:grid-cols-2">
            {textField('symptom')}
            {textField('cause')}
          </div>
          {textField('fix')}
        </>
      ) : (
        TEXT_KEYS.map((k) => textField(k))
      )}

      <div className={`rounded-2xl bg-[var(--surface)] p-3 ${compact ? '' : 'mb-3'}`}>
        <div className="mb-1 flex items-center justify-between text-sm font-semibold">
          <span>{t('capture.fields.steps')}</span>
          {dirty.has('steps') && <span className="text-xs font-normal text-[var(--green)]">{t('capture.fields.edited')}</span>}
        </div>
        <ol className="space-y-2">
          {vals.steps.map((s, i) => (
            <li key={i} className="flex gap-2">
              <span className="mt-2 w-5 shrink-0 text-right text-sm text-[var(--ink-faint)]">{i + 1}.</span>
              {editable ? (
                <>
                  <textarea rows={1} aria-label={`${t('capture.fields.steps')} ${i + 1}`} className={box} value={s}
                    placeholder={emptyPlaceholder ?? t('capture.fields.placeholder')}
                    onChange={(e) => set('steps', vals.steps.map((x, j) => (j === i ? e.target.value : x)))} />
                  <button type="button" aria-label={t('capture.fields.removeStep')}
                    className="h-10 w-10 shrink-0 rounded-full text-[var(--ink-muted)] hover:bg-[var(--line)]"
                    onClick={() => set('steps', vals.steps.filter((_, j) => j !== i))}>×</button>
                </>
              ) : (
                <span className="py-1">{s}</span>
              )}
            </li>
          ))}
        </ol>
        {editable && vals.steps.length < 20 && (
          <button type="button" className="mt-2 text-sm font-semibold text-[var(--green)]"
            onClick={() => set('steps', [...vals.steps, ''])}>+ {t('capture.fields.addStep')}</button>
        )}
        {!vals.steps.length && !editable && <p>—</p>}
      </div>

      <div className={`rounded-2xl border p-3 ${compact ? '' : 'mb-3'} ${vals.safety_note ? 'border-[var(--line)] bg-[var(--surface)]' : 'border-[var(--safety)] bg-[var(--safety-tint)]'}`}>
        <label htmlFor="f-safety_note" className="mb-1 block text-sm font-semibold">{t('capture.fields.safety_note')}</label>
        {editable ? (
          <textarea id="f-safety_note" rows={2} className={box} value={vals.safety_note ?? ''}
            placeholder={t('capture.fields.safetyPlaceholder')} onChange={(e) => set('safety_note', e.target.value)} />
        ) : (
          <p>{vals.safety_note || t('capture.fields.noSafety')}</p>
        )}
      </div>

      {(vals.parts?.length || vals.tools?.length || vals.downtime_min != null) && (
        <div className="rounded-2xl bg-[var(--surface)] p-3 text-sm">
          {!!vals.parts?.length && (
            <p><b>{t('capture.fields.parts')}:</b> {vals.parts.map((p) => [p.name, p.part_no, p.qty ? `×${p.qty}` : null].filter(Boolean).join(' ')).join(', ')}</p>
          )}
          {!!vals.tools?.length && <p><b>{t('capture.fields.tools')}:</b> {vals.tools.join(', ')}</p>}
          {vals.downtime_min != null && <p><b>{t('capture.fields.downtime_min')}:</b> {vals.downtime_min} min</p>}
        </div>
      )}
    </div>
  );
}
