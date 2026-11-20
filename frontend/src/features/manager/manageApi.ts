/**
 * Phase 4 API client + types for the manager screens W3–W8.
 * JSON calls use the Phase 0 `api()` helper; uploads (documents, breakdown logs) use fetch with the Supabase token.
 * Documents, log imports and jobs are Phase 1 endpoints; the rest is backend/app/manage.
 * ADAPT: if your helpers live elsewhere, fix the imports below — nothing else.
 */
import { api, type ApiOptions } from '../../lib/api';
import { supabase } from '../../lib/supabase';
import { errorCode, UploadError } from '../capture/captureApi';

export { errorCode };

const json = (method: ApiOptions['method'], body?: unknown): ApiOptions => ({ method, body });
const qs = (o: Record<string, string | number | boolean | null | undefined>) => {
  const p = new URLSearchParams();
  Object.entries(o).forEach(([k, v]) => { if (v !== null && v !== undefined && v !== '') p.set(k, String(v)); });
  const s = p.toString();
  return s ? `?${s}` : '';
};

/** Server message when there is one ("SH-0521 is already used in this plant."), else null. */
export function errorMessage(e: unknown): string | null {
  const any = e as Record<string, any> | null;
  return any?.message && !(e instanceof TypeError) ? String(any.message)
    : any?.error?.message ?? any?.detail?.error?.message ?? any?.body?.error?.message ?? any?.body?.detail?.error?.message ?? null;
}

async function upload<T>(path: string, form: FormData): Promise<T> {
  const { data } = await supabase.auth.getSession();
  const token = data.session?.access_token;
  const base = (import.meta as any).env?.VITE_API_URL ?? '/api';
  const res = await fetch(`${base}${path}`, { method: 'POST', headers: token ? { Authorization: `Bearer ${token}` } : undefined, body: form });
  if (!res.ok) {
    let code = 'upload_failed';
    let message = res.statusText;
    try {
      const b = await res.json();
      const err = b?.error ?? b?.detail?.error;
      code = err?.code ?? code;
      message = err?.message ?? message;
    } catch { /* not JSON */ }
    throw new UploadError(code, message);
  }
  return res.json();
}

// ================================================================ W8 People
export type Role = 'technician' | 'expert' | 'supervisor';
export type PersonStatus = 'new' | 'active' | 'deactivated';
export interface Person {
  id: string; name: string; employee_id: string | null; role: Role; is_admin: boolean; language: string;
  status: PersonStatus; login: 'pin' | 'email'; email: string | null; is_you: boolean;
  created_at: string | null; deactivated_at: string | null;
  last_active: string | null;   // latest of: signed in, asked a question, recorded a note
  approved_notes: number;
}
export type PinLogin = { method: 'pin'; employee_id: string | null; pin: string; plant_code?: string };
export type EmailLogin = { method: 'email'; email: string | null; temp_password: string };
export type Login = PinLogin | EmailLogin;
export interface NewPerson { name: string; role: Role; language: string; employee_id?: string; email?: string; is_admin?: boolean }

export const listPeople = () => api<{ items: Person[]; counts: Record<PersonStatus, number> }>('/admin/people');
export const addPerson = (b: NewPerson) => api<{ person: Person; login: Login; shown_once: true }>('/admin/people', json('POST', b));
export const updatePerson = (id: string, b: Partial<Pick<Person, 'name' | 'role' | 'language' | 'is_admin'>>) =>
  api<Person>(`/admin/people/${id}`, json('PATCH', b));
export const resetLogin = (id: string) => api<{ login: Login; shown_once: true }>(`/admin/people/${id}/reset-login`, json('POST'));
export const deactivatePerson = (id: string) => api<Person>(`/admin/people/${id}/deactivate`, json('POST'));
export const reactivatePerson = (id: string) => api<Person>(`/admin/people/${id}/reactivate`, json('POST'));

// ================================================================ W7 Machines
export interface MachineModel { id: string; model: string; type: string | null; oem: string | null; machines?: string[] }
export interface Machine {
  id: string; code: string; name: string | null; line: string | null;
  model: { id: string; model: string | null; type: string | null; oem: string | null } | null;
  approved_records: number; questions_30d: number; last_breakdown: { date: string | null; fault: string | null } | null;
  qr_url: string; sticker_printed_at: string | null; archived: boolean; archived_at: string | null;
}
export interface MachineInput {
  code: string; name?: string | null; line?: string | null; model_id?: string | null;
  new_model?: { model: string; type?: string | null; oem?: string | null } | null;
}
export interface Sticker { id: string; code: string; name: string | null; line: string | null; model: string | null; url: string; svg: string }

export const listMachines = (includeArchived = false) =>
  api<{ items: Machine[]; counts: { active: number; archived: number; stickers_missing: number } }>(`/admin/machines${qs({ include_archived: includeArchived || null })}`);
export const listModels = () => api<MachineModel[]>('/admin/machine-models');   // Phase 1
export const addModel = (b: { model: string; type?: string | null; oem?: string | null }) =>
  api<MachineModel>('/admin/machine-models', json('POST', b));
export const addMachine = (b: MachineInput) => api<Machine>('/admin/machines', json('POST', b));
export const updateMachine = (id: string, b: Partial<MachineInput>) => api<Machine>(`/admin/machines/${id}`, json('PATCH', b));
export const archiveMachine = (id: string) => api<Machine>(`/admin/machines/${id}/archive`, json('POST'));
export const restoreMachine = (id: string) => api<Machine>(`/admin/machines/${id}/restore`, json('POST'));
export const newQr = (id: string) => api<Machine>(`/admin/machines/${id}/new-qr`, json('POST'));
export const getStickers = (ids: string[]) => api<{ items: Sticker[] }>('/admin/machines/stickers', json('POST', { machine_ids: ids }));
export const markPrinted = (ids: string[]) => api<{ marked: number }>('/admin/machines/stickers/printed', json('POST', { machine_ids: ids }));

// ================================================================ W6 Knowledge base
export type Kind = 'E' | 'M' | 'H';
export interface KnowledgeItem {
  kind: Kind; source_type: 'record' | 'manual' | 'log'; id: string; title: string; machine: string | null;
  date: string | null; used: number; status: string;
  author?: string | null; approved_by?: string | null; origin?: string | null;           // E
  model?: string | null; sections?: number; pages?: number | null; quality_notes?: string | null; // M
  downtime_min?: number | null; technician?: string | null;                               // H
}
export interface KnowledgeStats {
  records: number; records_week: number; records_archived: number; manual_sections: number; documents: number;
  history: number; questions_30d: number; answered_30d: number; answered_rate_30d: number | null;
}
export interface KnowledgeQuery { kind: 'all' | Kind; machine?: string; q?: string; archived?: boolean; sort?: 'recent' | 'used' }

export const knowledgeStats = () => api<KnowledgeStats>('/manager/knowledge/stats');
export const knowledgeItems = (f: KnowledgeQuery) =>
  api<{ items: KnowledgeItem[]; count: number }>(`/manager/knowledge/items${qs({ kind: f.kind, machine: f.machine, q: f.q, archived: f.archived || null, sort: f.sort })}`);
export const archiveRecord = (id: string) => api<{ id: string; status: string }>(`/manager/knowledge/records/${id}/archive`, json('POST'));
export const restoreRecord = (id: string) => api<{ id: string; status: string; warning?: string }>(`/manager/knowledge/records/${id}/restore`, json('POST'));

// ================================================================ W3 Analytics
export type Days = 7 | 30 | 90;
export interface Analytics {
  days: Days;
  questions: { total: number; answered: number; no_answer: number; failed: number; voice: number; escalated: number; answered_rate: number | null; first_word_ms: number | null };
  feedback: { fixed: number; not_fixed: number; total: number };
  escalations: { created: number; answered: number; open_now: number; minutes_to_answer: number | null };
  notes: { sent: number; approved: number; rejected: number; pending_now: number; hours_to_review: number | null };
  per_day: { day: string; questions: number; answered: number; escalated: number }[];
  machines: { code: string; name: string | null; questions: number; no_answer: number; escalated: number }[];
  gaps: { id: string; question: string | null; status: string; machine: string | null; created_at: string; escalation_status: string | null }[];
  team: { id: string; name: string; role: Role; questions: number; notes_sent: number; notes_approved: number; answers_given: number; knowledge_used: number }[];
}
export const getAnalytics = (days: Days) => api<Analytics>(`/manager/analytics?days=${days}`);

// ================================================================ W4 Documents (Phase 1 endpoints)
export type DocStatus = 'uploaded' | 'parsing' | 'embedding' | 'ready' | 'failed' | string;
export interface DocumentRow {
  id: string; title: string; type: 'manual' | 'sop' | 'safety' | string; model: string | null; status: DocStatus;
  pages: number | null; chunks: number | null; quality_notes: string | null; error: string | null; created_at: string;
}
export interface Job { type: string; status: 'queued' | 'running' | 'done' | 'failed'; progress: number | null; error: string | null; updated_at: string }

export const listDocuments = () => api<DocumentRow[] | { items: DocumentRow[] }>('/admin/documents')
  .then((r) => (Array.isArray(r) ? r : r.items));
export const deleteDocument = (id: string) => api<void>(`/admin/documents/${id}`, { method: 'DELETE' });
export function uploadDocument(f: { file: File; title: string; type: string; model_id: string }, replace = false) {
  const form = new FormData();
  form.append('file', f.file);
  form.append('title', f.title);
  form.append('type', f.type);
  form.append('model_id', f.model_id);
  return upload<{ document_id: string; job_id: string }>(`/admin/documents${replace ? '?replace=true' : ''}`, form);
}
export const getJob = (id: string) => api<Job>(`/admin/jobs/${id}`);

// ================================================================ W5 Breakdown logs (Phase 1 endpoints + Phase 4 lists)
export const LOG_FIELDS = ['machine_code', 'fault', 'date', 'action', 'downtime_min', 'technician'] as const;
export type LogField = (typeof LOG_FIELDS)[number];
export type Mapping = Record<LogField, string | null>;
export interface LogAnalysis {
  import_id: string; header_row: number; columns: string[]; sample_rows: (string | number | null)[][] | Record<string, unknown>[];
  total_rows: number; suggested_mapping: Mapping; mapping_source: 'llm' | 'rules';
}
export interface LogImport {
  id: string; status: string; file_name?: string | null; mapping?: Mapping | null; rows_ok: number; rows_skipped: number;
  skipped?: { row: number; reason: string }[]; created_at?: string; created_by?: string | null;
}
export interface MaintenanceLog { id: string; date: string | null; machine: string | null; fault: string | null; action: string | null; downtime_min: number | null; technician: string | null; file_name: string | null }

export function uploadLog(file: File, force = false) {
  const form = new FormData();
  form.append('file', file);
  return upload<LogAnalysis>(`/admin/log-imports${force ? '?force=true' : ''}`, form);
}
export const confirmImport = (id: string, mapping: Mapping) => api<{ job_id: string }>(`/admin/log-imports/${id}/confirm`, json('POST', { mapping }));
export const getImport = (id: string) => api<LogImport>(`/admin/log-imports/${id}`);
export const importHistory = () => api<{ items: LogImport[] }>('/admin/log-imports');
export const maintenanceLogs = (machine?: string) => api<{ items: MaintenanceLog[] }>(`/admin/maintenance-logs${qs({ machine })}`);
