/**
 * W8 People (/manager/setup/people). Plant admins only.
 * Add technicians and experts (employee ID + PIN) and supervisors (email + temporary password), edit role or
 * language, reset a forgotten PIN, deactivate people who leave. Nobody is deleted: their repair notes keep their name.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  addPerson, deactivatePerson, errorCode, errorMessage, listPeople, reactivatePerson, resetLogin, updatePerson,
  type Login, type NewPerson, type Person, type PersonStatus, type Role,
} from '../manageApi';
import { Banner, Btn, Chip, Confirm, Dialog, Empty, Field, inputCls, Page, Search, Segmented, Spinner } from '../ui/kit';
import { LANGUAGES, langName } from '../ui/languages';
import LoginSlip from './LoginSlip';

type Filter = 'current' | PersonStatus | 'all';
const KEY = ['manage', 'people'];

function useAgo() {
  const { t, i18n } = useTranslation();
  return (iso: string | null) => {
    if (!iso) return t('manage.people.never');
    const days = Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000);
    if (days < 1) return t('manage.people.today');
    if (days < 30) return t('manage.people.daysAgo', { count: days });
    return new Date(iso).toLocaleDateString(i18n.language, { day: 'numeric', month: 'short' });
  };
}

function RoleChip({ p }: { p: Person }) {
  const { t } = useTranslation();
  return (
    <span className="flex flex-wrap gap-1">
      <Chip tone={p.role === 'expert' ? 'history' : p.role === 'supervisor' ? 'manual' : 'plain'}>{t(`manage.role.${p.role}`)}</Chip>
      {p.is_admin && <Chip tone="green">{t('manage.people.admin')}</Chip>}
    </span>
  );
}

function PersonForm({ person, onDone }: { person: Person | null; onDone: (r: { person: Person; login?: Login }) => void }) {
  const { t } = useTranslation();
  const editing = !!person;
  const [role, setRole] = useState<Role>(person?.role ?? 'technician');
  const [name, setName] = useState(person?.name ?? '');
  const [employeeId, setEmployeeId] = useState(person?.employee_id ?? '');
  const [email, setEmail] = useState('');
  const [language, setLanguage] = useState(person?.language ?? 'hi-IN');
  const [isAdmin, setIsAdmin] = useState(person?.is_admin ?? false);
  const save = useMutation({
    mutationFn: async () => {
      if (editing) {
        const b: Parameters<typeof updatePerson>[1] = { name: name.trim(), language };
        if (person!.role !== 'supervisor' && role !== person!.role && role !== 'supervisor') b.role = role;
        if (person!.role === 'supervisor' && isAdmin !== person!.is_admin) b.is_admin = isAdmin;
        return { person: await updatePerson(person!.id, b) };
      }
      const b: NewPerson = { name: name.trim(), role, language };
      if (role === 'supervisor') { b.email = email.trim(); b.is_admin = isAdmin; } else b.employee_id = employeeId.trim();
      const r = await addPerson(b);
      return { person: r.person, login: r.login };
    },
    onSuccess: onDone,
  });
  const code = save.error ? errorCode(save.error) : null;
  const fieldErr = (codes: string[]) => (code && codes.includes(code) ? errorMessage(save.error) ?? t(`manage.errors.${code}`, { defaultValue: t('manage.errors.generic') }) : undefined);
  const otherErr = code && !['bad_employee_id', 'employee_id_taken', 'employee_id_required', 'email_required', 'login_exists'].includes(code);
  const valid = name.trim().length >= 2 && (editing || (role === 'supervisor' ? /\S+@\S+\.\S+/.test(email) : employeeId.trim().length >= 2));

  return (
    <form id="person-form" className="space-y-4" onSubmit={(e) => { e.preventDefault(); if (valid) save.mutate(); }}>
      <fieldset>
        <legend className="mb-1.5 text-sm font-semibold">{t('manage.people.form.role')}</legend>
        <div className="grid grid-cols-3 gap-2">
          {(['technician', 'expert', 'supervisor'] as Role[]).map((r) => {
            const locked = editing && (person!.role === 'supervisor' ? r !== 'supervisor' : r === 'supervisor');
            return (
              <label key={r} className={`flex cursor-pointer flex-col rounded-xl border px-3 py-2 text-sm ${role === r ? 'border-[var(--green)] bg-[var(--green-tint)]' : 'border-[var(--line)]'} ${locked ? 'cursor-not-allowed opacity-40' : ''}`}>
                <input type="radio" name="role" value={r} checked={role === r} disabled={locked || (editing && person!.is_you)} onChange={() => setRole(r)} className="sr-only" />
                <span className="font-semibold">{t(`manage.role.${r}`)}</span>
                <span className="text-xs text-[var(--ink-muted)]">{t(`manage.people.form.roleHint.${r}`)}</span>
              </label>
            );
          })}
        </div>
        {editing && person!.role === 'supervisor' && <p className="mt-1 text-xs text-[var(--ink-muted)]">{t('manage.people.form.supervisorFixed')}</p>}
      </fieldset>
      <Field label={t('manage.people.form.name')}>
        {(id) => <input id={id} className={inputCls} value={name} onChange={(e) => setName(e.target.value)} autoComplete="off" maxLength={80} required />}
      </Field>
      {!editing && role !== 'supervisor' && (
        <Field label={t('manage.people.form.employeeId')} hint={t('manage.people.form.employeeIdHint')} error={fieldErr(['bad_employee_id', 'employee_id_taken', 'employee_id_required', 'login_exists'])}>
          {(id, d) => <input id={id} aria-describedby={d} className={`${inputCls} uppercase`} value={employeeId} onChange={(e) => setEmployeeId(e.target.value)} placeholder="SH-0521" maxLength={20} autoComplete="off" required />}
        </Field>
      )}
      {!editing && role === 'supervisor' && (
        <Field label={t('manage.people.form.email')} hint={t('manage.people.form.emailHint')} error={fieldErr(['email_required', 'login_exists'])}>
          {(id, d) => <input id={id} aria-describedby={d} type="email" className={inputCls} value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="off" required />}
        </Field>
      )}
      <Field label={t('manage.people.form.language')} hint={t('manage.people.form.languageHint')}>
        {(id, d) => (
          <select id={id} aria-describedby={d} className={inputCls} value={language} onChange={(e) => setLanguage(e.target.value)}>
            {LANGUAGES.map((l) => <option key={l.code} value={l.code}>{l.name} · {l.native}</option>)}
          </select>
        )}
      </Field>
      {role === 'supervisor' && (
        <label className="flex items-start gap-3 rounded-xl border border-[var(--line)] p-3">
          <input type="checkbox" className="mt-1 h-4 w-4 accent-[var(--green)]" checked={isAdmin} disabled={editing && person!.is_you} onChange={(e) => setIsAdmin(e.target.checked)} />
          <span>
            <span className="block font-semibold">{t('manage.people.form.admin')}</span>
            <span className="text-sm text-[var(--ink-muted)]">{t('manage.people.form.adminHint')}</span>
          </span>
        </label>
      )}
      {otherErr && <Banner tone="alert">{errorMessage(save.error) ?? t('manage.errors.generic')}</Banner>}
      <div className="flex justify-end">
        <Btn type="submit" kind="primary" busy={save.isPending} disabled={!valid}>{editing ? t('manage.common.save') : t('manage.people.form.create')}</Btn>
      </div>
    </form>
  );
}

export default function PeoplePage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const ago = useAgo();
  const q = useQuery({ queryKey: KEY, queryFn: listPeople });
  const [filter, setFilter] = useState<Filter>('current');
  const [search, setSearch] = useState('');
  const [form, setForm] = useState<{ person: Person | null } | null>(null);
  const [slip, setSlip] = useState<{ login: Login; name: string } | null>(null);
  const [confirm, setConfirm] = useState<{ kind: 'reset' | 'deactivate' | 'reactivate'; p: Person } | null>(null);
  const refresh = () => qc.invalidateQueries({ queryKey: KEY });

  const act = useMutation({
    mutationFn: async ({ kind, p }: { kind: 'reset' | 'deactivate' | 'reactivate'; p: Person }) =>
      kind === 'reset' ? resetLogin(p.id) : kind === 'deactivate' ? deactivatePerson(p.id) : reactivatePerson(p.id),
    onSuccess: (r, v) => {
      setConfirm(null);
      if ('shown_once' in r) setSlip({ login: r.login, name: v.p.name });   // shown once, never cached
      refresh();
    },
  });

  const items = useMemo(() => {
    const all = q.data?.items ?? [];
    const s = search.trim().toLowerCase();
    return all.filter((p) =>
      (filter === 'all' || (filter === 'current' ? p.status !== 'deactivated' : p.status === filter)) &&
      (!s || p.name.toLowerCase().includes(s) || (p.employee_id ?? '').toLowerCase().includes(s) || (p.email ?? '').toLowerCase().includes(s)));
  }, [q.data, filter, search]);
  const c = q.data?.counts;

  return (
    <Page title={t('manage.people.title')}
      subtitle={c ? t('manage.people.summary', { active: c.active + c.new, new: c.new }) : t('manage.people.subtitle')}
      actions={<Btn kind="primary" onClick={() => setForm({ person: null })}>{t('manage.people.add')}</Btn>}>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <Segmented label={t('manage.people.title')} value={filter} onChange={setFilter} options={[
          { value: 'current', label: t('manage.people.filter.current'), count: c ? c.active + c.new : undefined },
          { value: 'new', label: t('manage.people.filter.new'), count: c?.new },
          { value: 'deactivated', label: t('manage.people.filter.deactivated'), count: c?.deactivated },
          { value: 'all', label: t('manage.people.filter.all') },
        ]} />
        <Search value={search} onChange={setSearch} placeholder={t('manage.people.search')} />
      </div>

      {q.isLoading ? <Spinner size={24} /> : q.isError ? <Banner tone="alert">{t('manage.errors.load')}</Banner> : !items.length ? (
        <Empty title={search ? t('manage.people.noMatch') : t(`manage.people.empty.${filter}`)} />
      ) : (
        <div className="overflow-hidden rounded-[var(--radius-card,22px)] bg-[var(--white)]">
          <table className="w-full text-left text-[15px]">
            <thead className="border-b border-[var(--line)] text-xs text-[var(--ink-muted)]">
              <tr>
                <th scope="col" className="px-5 py-3 font-semibold">{t('manage.people.col.person')}</th>
                <th scope="col" className="px-3 py-3 font-semibold">{t('manage.people.col.role')}</th>
                <th scope="col" className="px-3 py-3 font-semibold">{t('manage.people.col.language')}</th>
                <th scope="col" className="px-3 py-3 font-semibold">{t('manage.people.col.signsIn')}</th>
                <th scope="col" className="px-3 py-3 font-semibold">{t('manage.people.col.lastActive')}</th>
                <th scope="col" className="px-3 py-3 text-right font-semibold">{t('manage.people.col.notes')}</th>
                <th scope="col" className="px-5 py-3"><span className="sr-only">{t('manage.common.actions')}</span></th>
              </tr>
            </thead>
            <tbody>
              {items.map((p) => {
                const last = p.last_active;
                const off = p.status === 'deactivated';
                return (
                  <tr key={p.id} className={`border-b border-[var(--line)] last:border-0 ${off ? 'text-[var(--ink-faint)]' : ''}`}>
                    <td className="px-5 py-3">
                      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 font-semibold">
                        <span className="whitespace-nowrap">{p.name}</span>
                        {p.is_you && <span className="text-xs font-normal text-[var(--ink-muted)]">({t('manage.people.you')})</span>}
                        {p.status === 'new' && <Chip tone="safety">{t('manage.people.status.new')}</Chip>}
                        {off && <Chip>{t('manage.people.status.deactivated')}</Chip>}
                      </div>
                      <div className="text-sm text-[var(--ink-muted)]">{p.employee_id ?? p.email}</div>
                    </td>
                    <td className="px-3 py-3"><RoleChip p={p} /></td>
                    <td className="px-3 py-3">{langName(p.language)}</td>
                    <td className="whitespace-nowrap px-3 py-3 text-sm">{p.login === 'pin' ? t('manage.people.loginPin') : t('manage.people.loginEmail')}</td>
                    <td className="whitespace-nowrap px-3 py-3 text-sm">{ago(last)}</td>
                    <td className="px-3 py-3 text-right tabular-nums">{p.approved_notes || '–'}</td>
                    <td className="px-5 py-3">
                      <div className="flex justify-end gap-1">
                        {off ? (
                          <Btn small kind="ghost" onClick={() => setConfirm({ kind: 'reactivate', p })}>{t('manage.people.reactivate')}</Btn>
                        ) : (
                          <>
                            <Btn small kind="ghost" onClick={() => setForm({ person: p })}>{t('manage.common.edit')}</Btn>
                            {!p.is_you && <Btn small kind="ghost" onClick={() => setConfirm({ kind: 'reset', p })}>{p.login === 'pin' ? t('manage.people.resetPin') : t('manage.people.resetPassword')}</Btn>}
                            {!p.is_you && <Btn small kind="ghost" className="!text-[var(--alert)]" onClick={() => setConfirm({ kind: 'deactivate', p })}>{t('manage.people.deactivate')}</Btn>}
                          </>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <Dialog open={!!form} onClose={() => setForm(null)} title={form?.person ? t('manage.people.editTitle', { name: form.person.name }) : t('manage.people.addTitle')}>
        {form && <PersonForm key={form.person?.id ?? 'new'} person={form.person} onDone={(r) => {
          setForm(null);
          refresh();
          if (r.login) setSlip({ login: r.login, name: r.person.name });
        }} />}
      </Dialog>

      {confirm && (
        <Confirm open onClose={() => { setConfirm(null); act.reset(); }} busy={act.isPending} danger={confirm.kind === 'deactivate'}
          title={t(`manage.people.confirm.${confirm.kind}.title`, { name: confirm.p.name })}
          confirmLabel={t(`manage.people.confirm.${confirm.kind}.cta`)}
          onConfirm={() => act.mutate(confirm)}
          body={<>
            <p>{t(`manage.people.confirm.${confirm.kind}.body${confirm.kind === 'reset' && confirm.p.login === 'email' ? 'Email' : ''}`, { name: confirm.p.name })}</p>
            {act.isError && <div className="mt-3"><Banner tone="alert">{errorMessage(act.error) ?? t('manage.errors.generic')}</Banner></div>}
          </>} />
      )}

      <LoginSlip login={slip?.login ?? null} name={slip?.name ?? ''} onClose={() => setSlip(null)} />
    </Page>
  );
}
