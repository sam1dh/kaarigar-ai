/**
 * Phase 2 API client + types.
 * Uses the Phase 0 `api()` helper for JSON calls and a small fetch for the audio upload (multipart).
 * ADAPT: if your helpers live elsewhere, fix the two imports below — nothing else.
 */
import { api } from '../../lib/api';
import { supabase } from '../../lib/supabase';

// ---------------------------------------------------------------- types
export type Stage = 'queued' | 'transcribing' | 'extracting' | 'checking' | 'translating' | 'ready' | 'failed' | null;
export type Status = 'draft' | 'expert_review' | 'pending' | 'approved' | 'rejected';

export interface Part { name: string; part_no: string | null; qty: number | null }

export interface RecordFields {
  symptom: string | null;
  cause: string | null;
  fix: string | null;
  steps: string[] | null;
  parts: Part[] | null;
  tools: string[] | null;
  safety_note: string | null;
  downtime_min: number | null;
  missing: string[] | null;
  is_repair_note: boolean | null;
}

export interface LocalFields {
  symptom: string | null;
  cause: string | null;
  fix: string | null;
  steps: string[];
  safety_note: string | null;
  issues: string[];
  summary: string | null;
  language: string;
}

export interface Issue { field: string; severity: 'high' | 'medium' | 'low'; message: string }
export interface AICheck { issues: Issue[]; safety_ok: boolean; summary: string; manual_sources?: string[] }

export interface CaptureRecord {
  id: string;
  machine: { id: string; code: string; name: string | null; line: string | null; model: string | null };
  author: { id: string; name: string | null };
  reviewer: { id: string; name: string | null } | null;
  status: Status;
  stage: Stage;
  processing: boolean;
  error: { code: string; retryable: boolean } | null;
  language: string;
  audio_seconds: number | null;
  audio_url: string | null;
  transcript_en: string | null;
  fields: RecordFields;
  fields_local: LocalFields | null;
  ai_check: AICheck | null;
  reject_reason: string | null;
  created_at: string;
  submitted_at: string | null;
  reviewed_at: string | null;
  can: { submit: boolean; retry: boolean; discard: boolean; review: boolean };
}

export interface QueueItem {
  id: string;
  machine: { code: string; name: string | null };
  author: { id: string; name: string | null };
  submitted_at: string | null;
  symptom: string | null;
  fix: string | null;
  language: string | null;
  audio_seconds: number | null;
  issues_high: number;
  issues_total: number;
  safety_ok: boolean | null;
}

export type EditableKey = 'symptom' | 'cause' | 'fix' | 'steps' | 'parts' | 'tools' | 'safety_note' | 'downtime_min';
export type FieldEdits = Partial<Pick<RecordFields, EditableKey>>;

// ---------------------------------------------------------------- helpers
type Call = <T>(path: string, init?: { method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE"; body?: unknown }) => Promise<T>;
const call = api as unknown as Call;

// ADAPT: Phase 0's api() serialises `body` itself and adds the auth header.
const json = <T,>(path: string, method: "GET" | "POST" | "PUT" | "PATCH" | "DELETE", body?: unknown) =>
  call<T>(path, { method, body });

/** Reads the error code from whatever shape the Phase 0 helper throws, or from our own upload errors. */
export function errorCode(e: unknown): string {
  const any = e as Record<string, any> | null;
  return (
    any?.code ??
    any?.error?.code ??
    any?.detail?.error?.code ??
    any?.body?.error?.code ??
    any?.body?.detail?.error?.code ??
    'network'
  );
}

export class UploadError extends Error {
  constructor(public code: string, message: string) {
    super(message);
  }
}

// ---------------------------------------------------------------- expert (phone)
export async function createRecord(machineCode: string, audio: Blob, mimeType: string): Promise<{ record_id: string }> {
  const ext = mimeType.includes('mp4') ? 'm4a' : mimeType.includes('ogg') ? 'ogg' : 'webm';
  const form = new FormData();
  form.append('machine_code', machineCode);
  form.append('audio', new File([audio], `note.${ext}`, { type: mimeType.split(';')[0] || 'audio/webm' }));
  const { data } = await supabase.auth.getSession();
  const token = data.session?.access_token;
  const base = (import.meta as any).env?.VITE_API_URL ?? '/api';
  const res = await fetch(`${base}/capture/records`, {
    method: 'POST',
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    body: form,
  });
  if (!res.ok) {
    let code = 'upload_failed';
    let message = res.statusText;
    try {
      const body = await res.json();
      const err = body?.error ?? body?.detail?.error;
      code = err?.code ?? code;
      message = err?.message ?? message;
    } catch {
      /* not JSON */
    }
    throw new UploadError(code, message);
  }
  return res.json();
}

export const getRecord = (id: string) => call<CaptureRecord>(`/capture/records/${id}`);
export const listMyRecords = (machineCode?: string, limit = 10) =>
  call<{ items: CaptureRecord[] }>(
    `/capture/records?limit=${limit}${machineCode ? `&machine_code=${encodeURIComponent(machineCode)}` : ''}`,
  );
export const submitRecord = (id: string, edits: FieldEdits, editLanguage: string) =>
  json<CaptureRecord>(`/capture/records/${id}/submit`, 'POST', { edits, edit_language: editLanguage });
export const retryRecord = (id: string) => json<{ record_id: string }>(`/capture/records/${id}/retry`, 'POST');
export const discardRecord = (id: string) => call<unknown>(`/capture/records/${id}`, { method: 'DELETE' });

// ---------------------------------------------------------------- supervisor (web)
export const getReviewQueue = () => call<{ items: QueueItem[]; count: number }>('/manager/review-queue');
export const getReviewCount = () => call<{ count: number }>('/manager/review-queue/count');
export const getReviewRecord = (id: string) => call<CaptureRecord>(`/manager/records/${id}`);
export const approveRecord = (id: string, edits: FieldEdits) =>
  json<CaptureRecord>(`/manager/records/${id}/approve`, 'POST', { edits });
export const rejectRecord = (id: string, reason: string) =>
  json<CaptureRecord>(`/manager/records/${id}/reject`, 'POST', { reason });

// ---------------------------------------------------------------- me
export interface Me { name: string; role: 'technician' | 'expert' | 'supervisor'; is_admin: boolean; language: string }
export const getMe = () => call<Me>('/auth/me');
