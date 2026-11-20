/**
 * W7 Machines (/manager/setup/machines). Plant admins only.
 * Add or edit machines, print QR stickers (they open the machine screen on the phone), replace a lost sticker
 * with "New QR" (the old one stops working), archive machines that left the floor.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import {
  addMachine, addModel, archiveMachine, errorCode, errorMessage, listMachines, listModels, newQr, restoreMachine, updateMachine,
  type Machine, type MachineInput,
} from '../manageApi';
import { Banner, Btn, Chip, Confirm, dateFmt, Dialog, Empty, Field, heading, inputCls, Page, Search, Segmented, Spinner } from '../ui/kit';

const KEY = ['manage', 'machines'];
const NEW = '__new__';

function MachineForm({ machine, onDone }: { machine: Machine | null; onDone: (m: Machine) => void }) {
  const { t } = useTranslation();
  const models = useQuery({ queryKey: ['manage', 'models'], queryFn: listModels, staleTime: 60_000 });
  const [code, setCode] = useState(machine?.code ?? '');
  const [name, setName] = useState(machine?.name ?? '');
  const [line, setLine] = useState(machine?.line ?? '');
  const [modelId, setModelId] = useState(machine?.model?.id ?? '');
  const [newModel, setNewModel] = useState('');
  const [newType, setNewType] = useState('');
  const qc = useQueryClient();
  const save = useMutation({
    mutationFn: () => {
      const b: MachineInput = { code: code.trim(), name: name.trim() || null, line: line.trim() || null };
      if (modelId === NEW) b.new_model = { model: newModel.trim(), type: newType.trim() || null };
      else b.model_id = modelId || null;
      if (machine) {
        const patch: Partial<MachineInput> = { name: b.name, line: b.line };
        if (b.code.toUpperCase() !== machine.code) patch.code = b.code;
        if (modelId === NEW) {   // PATCH takes a model id, so create the model first
          return addModel({ model: newModel.trim(), type: newType.trim() || null })
            .then((m) => updateMachine(machine.id, { ...patch, model_id: m.id }));
        }
        if ((machine.model?.id ?? '') !== modelId) patch.model_id = modelId || null;
        return updateMachine(machine.id, patch);
      }
      return addMachine(b);
    },
    onSuccess: (m) => { qc.invalidateQueries({ queryKey: ['manage', 'models'] }); onDone(m); },
  });
  const code_ = save.error ? errorCode(save.error) : null;
  const codeErr = code_ === 'bad_code' || code_ === 'code_taken' ? errorMessage(save.error) ?? t(`manage.errors.${code_}`) : undefined;
  const valid = code.trim().length >= 2 && (modelId !== NEW || newModel.trim().length > 0);

  return (
    <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); if (valid) save.mutate(); }}>
      <div className="grid grid-cols-[160px_1fr] gap-3">
        <Field label={t('manage.machines.form.code')} error={codeErr} hint={!codeErr ? t('manage.machines.form.codeHint') : undefined}>
          {(id, d) => <input id={id} aria-describedby={d} className={`${inputCls} uppercase`} style={heading} value={code} onChange={(e) => setCode(e.target.value)} placeholder="HP-07" maxLength={16} required autoComplete="off" />}
        </Field>
        <Field label={t('manage.machines.form.name')}>
          {(id) => <input id={id} className={inputCls} value={name} onChange={(e) => setName(e.target.value)} placeholder={t('manage.machines.form.namePlaceholder')} maxLength={80} />}
        </Field>
      </div>
      <Field label={t('manage.machines.form.line')}>
        {(id) => <input id={id} className={inputCls} value={line} onChange={(e) => setLine(e.target.value)} placeholder="Line 2" maxLength={40} />}
      </Field>
      <Field label={t('manage.machines.form.model')} hint={t('manage.machines.form.modelHint')}>
        {(id, d) => (
          <select id={id} aria-describedby={d} className={inputCls} value={modelId} onChange={(e) => setModelId(e.target.value)}>
            <option value="">{t('manage.machines.form.noModel')}</option>
            {(models.data ?? []).map((m) => <option key={m.id} value={m.id}>{m.model}{m.type ? ` · ${m.type}` : ''}</option>)}
            <option value={NEW}>{t('manage.machines.form.newModel')}</option>
          </select>
        )}
      </Field>
      {modelId === NEW && (
        <div className="grid grid-cols-2 gap-3 rounded-xl bg-[var(--surface)] p-3">
          <Field label={t('manage.machines.form.modelName')}>
            {(id) => <input id={id} className={inputCls} value={newModel} onChange={(e) => setNewModel(e.target.value)} placeholder="HPX-200" maxLength={60} required />}
          </Field>
          <Field label={t('manage.machines.form.modelType')}>
            {(id) => <input id={id} className={inputCls} value={newType} onChange={(e) => setNewType(e.target.value)} placeholder={t('manage.machines.form.modelTypePlaceholder')} maxLength={60} />}
          </Field>
        </div>
      )}
      {save.isError && !codeErr && <Banner tone="alert">{errorMessage(save.error) ?? t('manage.errors.generic')}</Banner>}
      <div className="flex justify-end">
        <Btn type="submit" kind="primary" busy={save.isPending} disabled={!valid}>{machine ? t('manage.common.save') : t('manage.machines.form.create')}</Btn>
      </div>
    </form>
  );
}

export default function MachinesPage() {
  const { t, i18n } = useTranslation();
  const nav = useNavigate();
  const qc = useQueryClient();
  const [view, setView] = useState<'active' | 'archived'>('active');
  const [search, setSearch] = useState('');
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [form, setForm] = useState<{ machine: Machine | null } | null>(null);
  const [confirm, setConfirm] = useState<{ kind: 'archive' | 'restore' | 'newqr'; m: Machine } | null>(null);
  const q = useQuery({ queryKey: [...KEY, view], queryFn: () => listMachines(view === 'archived') });
  const refresh = () => qc.invalidateQueries({ queryKey: KEY });

  const act = useMutation({
    mutationFn: ({ kind, m }: { kind: 'archive' | 'restore' | 'newqr'; m: Machine }) =>
      kind === 'archive' ? archiveMachine(m.id) : kind === 'restore' ? restoreMachine(m.id) : newQr(m.id),
    onSuccess: (_, v) => {
      setConfirm(null);
      refresh();
      if (v.kind === 'newqr') nav(`/manager/setup/machines/stickers?ids=${v.m.id}`);
    },
  });

  const items = useMemo(() => {
    const s = search.trim().toLowerCase();
    return (q.data?.items ?? []).filter((m) => (view === 'archived' ? m.archived : !m.archived) &&
      (!s || [m.code, m.name, m.line, m.model?.model].some((x) => (x ?? '').toLowerCase().includes(s))));
  }, [q.data, view, search]);
  const counts = q.data?.counts;
  const allPicked = items.length > 0 && items.every((m) => picked.has(m.id));
  const toggle = (id: string) => setPicked((p) => { const n = new Set(p); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  const pickMissing = () => setPicked(new Set(items.filter((m) => !m.sticker_printed_at).map((m) => m.id)));

  return (
    <Page title={t('manage.machines.title')}
      subtitle={counts ? t('manage.machines.summary', { count: counts.active, missing: counts.stickers_missing }) : undefined}
      actions={<>
        {view === 'active' && picked.size > 0 && (
          <Btn onClick={() => nav(`/manager/setup/machines/stickers?ids=${[...picked].join(',')}`)}>{t('manage.machines.printSelected', { count: picked.size })}</Btn>
        )}
        <Btn kind="primary" onClick={() => setForm({ machine: null })}>{t('manage.machines.add')}</Btn>
      </>}>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-3">
          <Segmented label={t('manage.machines.title')} value={view} onChange={(v) => { setView(v); setPicked(new Set()); }} options={[
            { value: 'active', label: t('manage.machines.filter.active'), count: counts?.active },
            { value: 'archived', label: t('manage.machines.filter.archived'), count: view === 'archived' ? counts?.archived : undefined },
          ]} />
          {view === 'active' && !!counts?.stickers_missing && <Btn small kind="ghost" onClick={pickMissing}>{t('manage.machines.pickMissing', { count: counts.stickers_missing })}</Btn>}
        </div>
        <Search value={search} onChange={setSearch} placeholder={t('manage.machines.search')} />
      </div>

      {q.isLoading ? <Spinner size={24} /> : q.isError ? <Banner tone="alert">{t('manage.errors.load')}</Banner> : !items.length ? (
        <Empty title={search ? t('manage.machines.noMatch') : t(`manage.machines.empty.${view}`)}>{!search && view === 'active' && t('manage.machines.emptyHint')}</Empty>
      ) : (
        <div className="overflow-hidden rounded-[var(--radius-card,22px)] bg-[var(--white)]">
          <table className="w-full text-left text-[15px]">
            <thead className="border-b border-[var(--line)] text-xs text-[var(--ink-muted)]">
              <tr>
                {view === 'active' && (
                  <th scope="col" className="w-12 py-3 pl-5">
                    <input type="checkbox" className="h-4 w-4 accent-[var(--green)]" checked={allPicked} aria-label={t('manage.machines.pickAll')}
                      onChange={() => setPicked(allPicked ? new Set() : new Set(items.map((m) => m.id)))} />
                  </th>
                )}
                <th scope="col" className="px-3 py-3 font-semibold">{t('manage.machines.col.machine')}</th>
                <th scope="col" className="px-3 py-3 font-semibold">{t('manage.machines.col.model')}</th>
                <th scope="col" className="px-3 py-3 text-right font-semibold">{t('manage.machines.col.repairs')}</th>
                <th scope="col" className="px-3 py-3 text-right font-semibold">{t('manage.machines.col.questions')}</th>
                <th scope="col" className="px-3 py-3 font-semibold">{t('manage.machines.col.lastBreakdown')}</th>
                <th scope="col" className="px-3 py-3 font-semibold">{t('manage.machines.col.sticker')}</th>
                <th scope="col" className="px-5 py-3"><span className="sr-only">{t('manage.common.actions')}</span></th>
              </tr>
            </thead>
            <tbody>
              {items.map((m) => (
                <tr key={m.id} className={`border-b border-[var(--line)] last:border-0 ${picked.has(m.id) ? 'bg-[var(--green-tint)]/40' : ''}`}>
                  {view === 'active' && (
                    <td className="py-3 pl-5">
                      <input type="checkbox" className="h-4 w-4 accent-[var(--green)]" checked={picked.has(m.id)} onChange={() => toggle(m.id)} aria-label={t('manage.machines.pick', { code: m.code })} />
                    </td>
                  )}
                  <td className="min-w-[170px] px-3 py-3">
                    <div className="text-lg font-semibold leading-tight text-[var(--green-deep)]" style={heading}>{m.code}</div>
                    <div className="text-sm text-[var(--ink-muted)]">{[m.name, m.line].filter(Boolean).join(' · ') || '–'}</div>
                  </td>
                  <td className="min-w-[120px] px-3 py-3 text-sm">{m.model ? <>{m.model.model}{m.model.type && <span className="text-[var(--ink-muted)]"> · {m.model.type}</span>}</> : <span className="text-[var(--ink-faint)]">{t('manage.machines.noModel')}</span>}</td>
                  <td className="px-3 py-3 text-right tabular-nums">{m.approved_records}</td>
                  <td className="px-3 py-3 text-right tabular-nums">{m.questions_30d}</td>
                  <td className="max-w-[200px] px-3 py-3 text-sm">
                    {m.last_breakdown ? <><span className="text-[var(--ink-muted)]">{dateFmt(m.last_breakdown.date, i18n.language)}</span> <span className="line-clamp-1">{m.last_breakdown.fault}</span></> : <span className="text-[var(--ink-faint)]">–</span>}
                  </td>
                  <td className="whitespace-nowrap px-3 py-3 text-sm">
                    {m.archived ? <Chip>{t('manage.machines.archivedOn', { date: dateFmt(m.archived_at, i18n.language) })}</Chip>
                      : m.sticker_printed_at ? <span className="text-[var(--ink-muted)]">{t('manage.machines.printedOn', { date: dateFmt(m.sticker_printed_at, i18n.language) })}</span>
                      : <Chip tone="safety">{t('manage.machines.notPrinted')}</Chip>}
                  </td>
                  <td className="px-5 py-3">
                    <div className="flex justify-end gap-1">
                      {m.archived ? (
                        <Btn small kind="ghost" onClick={() => setConfirm({ kind: 'restore', m })}>{t('manage.machines.restore')}</Btn>
                      ) : (
                        <>
                          <Btn small kind="ghost" onClick={() => setForm({ machine: m })}>{t('manage.common.edit')}</Btn>
                          <Btn small kind="ghost" onClick={() => nav(`/manager/setup/machines/stickers?ids=${m.id}`)}>{t('manage.machines.sticker')}</Btn>
                          <Btn small kind="ghost" onClick={() => setConfirm({ kind: 'newqr', m })}>{t('manage.machines.newQr')}</Btn>
                          <Btn small kind="ghost" className="!text-[var(--alert)]" onClick={() => setConfirm({ kind: 'archive', m })}>{t('manage.machines.archive')}</Btn>
                        </>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <Dialog open={!!form} onClose={() => setForm(null)} title={form?.machine ? t('manage.machines.editTitle', { code: form.machine.code }) : t('manage.machines.addTitle')}>
        {form && <MachineForm key={form.machine?.id ?? 'new'} machine={form.machine} onDone={(m) => {
          setForm(null);
          refresh();
          if (!form.machine) nav(`/manager/setup/machines/stickers?ids=${m.id}`);   // new machine → print its sticker
        }} />}
      </Dialog>

      {confirm && (
        <Confirm open onClose={() => { setConfirm(null); act.reset(); }} busy={act.isPending} danger={confirm.kind !== 'restore'}
          title={t(`manage.machines.confirm.${confirm.kind}.title`, { code: confirm.m.code })}
          confirmLabel={t(`manage.machines.confirm.${confirm.kind}.cta`)}
          onConfirm={() => act.mutate(confirm)}
          body={<>
            <p>{t(`manage.machines.confirm.${confirm.kind}.body`, { code: confirm.m.code })}</p>
            {act.isError && <div className="mt-3"><Banner tone="alert">{errorMessage(act.error) ?? t('manage.errors.generic')}</Banner></div>}
          </>} />
      )}
    </Page>
  );
}
