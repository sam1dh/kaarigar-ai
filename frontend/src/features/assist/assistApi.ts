/**
 * Phase 3 API client + types.
 * JSON calls use the Phase 0 `api()` helper. /assist/ask streams Server-Sent Events, so it uses fetch
 * with the Supabase session token (EventSource can't POST or send headers).
 * ADAPT: if your helpers live elsewhere, fix the two imports below — nothing else.
 */
import { api } from '../../lib/api';
import { supabase } from '../../lib/supabase';
import { UploadError } from '../capture/captureApi';

// ---------------------------------------------------------------- types
export type Label = 'E' | 'M' | 'H';
export type QueryStatus = 'answering' | 'answered' | 'no_answer' | 'failed' | 'cancelled';
export type Stage = 'queued' | 'listening' | 'understanding' | 'searching' | 'writing';
export type Outcome = 'fixed' | 'not_fixed' | 'call_supervisor';

export interface Source {
  ref: string;              // E1, M2, H1
  label: Label;
  source_type: 'record' | 'manual' | 'log';
  source_id: string;
  chunk_id: string | null;
  title: string;
  page: number | null;
  same_machine: boolean;
  seed_key: string | null;
  snippet: string;
}

export interface Item { text: string; refs: string[]; n?: number }
export interface AnswerParts {
  no_answer: boolean;
  safety: Item[];
  steps: Item[];
  check: Item | null;
  refs_used: string[];
}

export interface MachineRef { code: string; name: string | null; model: string | null; line?: string | null; type?: string | null }
export interface Person { id: string; name: string | null }

export interface ReplyRecord {
  id: string;
  status: string;
  stage: string | null;
  language: string | null;
  fields: { symptom: string | null; cause: string | null; fix: string | null; steps: string[] | null; safety_note: string | null };
  audio_url: string | null;
}

export interface LocalFields {
  symptom: string | null; cause: string | null; fix: string | null; steps: string[]; safety_note: string | null;
}

export interface Escalation {
  id: string;
  status: 'open' | 'answered' | 'closed';
  created_at: string;
  answered_at: string | null;
  closed_at: string | null;
  close_reason?: string | null;
  machine: MachineRef | null;
  asked_by: Person | null;
  assigned_to: Person | null;
  replied_by: Person | null;
  question: { original: string | null; en: string | null; language: string | null };
  answer_status: QueryStatus | null;
  feedback: Outcome | null;
  has_note: boolean;
  reply_in_progress: boolean;
}

export interface EscalationDetail extends Escalation {
  query_id: string;
  note: string | null;
  assigned_at: string | null;
  kaarigar: {
    status: QueryStatus | null;
    answer_en: string | null;
    answer_local: string | null;
    parts: AnswerParts | null;
    sources: Source[];
    confidence: number | null;
    asked_at: string | null;
  };
  reply: {
    text: string | null;
    record: ReplyRecord | null;
    local?: { language: string; record_id: string | null; fields: LocalFields | null; text: string | null } | null;
  };
}

export interface QueryView {
  id: string;
  status: QueryStatus;
  created_at: string;
  machine: MachineRef | null;
  language: string | null;
  input_mode: 'voice' | 'text' | null;
  question: { original: string | null; en: string | null };
  answer: { parts: AnswerParts | null; text: string | null; en: string | null };
  sources: Source[];
  confidence: number | null;
  suggest_escalate: boolean;
  error: { code: string } | null;
  feedback: Outcome | null;
  escalation: (Partial<EscalationDetail> & { id: string; status: Escalation['status'] }) | null;
  can: { feedback: boolean; escalate: boolean; read_aloud: boolean };
}

export interface QueryListItem {
  id: string;
  status: QueryStatus;
  created_at: string;
  machine: MachineRef | null;
  question: { original: string | null; en: string | null };
  first_step: string | null;
  feedback: Outcome | null;
  escalation: { id: string; status: Escalation['status']; assigned_to: Person | null } | null;
}

export interface RecordSource {
  type: 'record'; id: string; machine: MachineRef | null; author: Person; approved_by: string | null; date: string | null;
  fields: ReplyRecord['fields']; local: LocalFields | null; audio_url: string | null; audio_seconds: number | null;
}
export interface ManualSource {
  type: 'manual'; id: string; title: string; model: string | null; page: number | null; pages: number | null;
  sections: { section: string | null; text: string; page: number | null }[]; pdf_url: string | null;
}
export interface LogSource {
  type: 'log'; id: string; machine: MachineRef | null; date: string | null; fault: string | null; action: string | null;
  downtime_min: number | null; technician: string | null;
}
export type SourceDetail = RecordSource | ManualSource | LogSource;

export interface Expert { id: string; name: string; role: string; language: string | null; open_assigned: number; approved_records: number }

// ---------------------------------------------------------------- helpers
type Call = <T>(path: string, init?: RequestInit) => Promise<T>;
const call = api as unknown as Call;
const json = <T,>(path: string, method: string, body?: unknown) =>
  call<T>(path, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });

export const apiBase = () => ((import.meta as any).env?.VITE_API_URL ?? '/api') as string;

async function authHeaders(): Promise<Record<string, string>> {
  const { data } = await supabase.auth.getSession();
  const token = data.session?.access_token;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function errorFrom(res: Response, fallback: string): Promise<UploadError> {
  let code = fallback;
  let message = res.statusText;
  try {
    const body = await res.json();
    const err = body?.error ?? body?.detail?.error;
    code = err?.code ?? code;
    message = err?.message ?? message;
  } catch {
    /* not JSON */
  }
  return new UploadError(code, message);
}

const audioFile = (blob: Blob, mimeType: string) => {
  const ext = mimeType.includes('mp4') ? 'm4a' : mimeType.includes('ogg') ? 'ogg' : 'webm';
  return new File([blob], `question.${ext}`, { type: mimeType.split(';')[0] || 'audio/webm' });
};

// ---------------------------------------------------------------- SSE
export interface SSEMessage { event: string; data: any }

/** Reads a text/event-stream body and calls `onMessage` for every event. Ignores `: ping` comments. */
export async function readSSE(body: ReadableStream<Uint8Array>, onMessage: (m: SSEMessage) => void) {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buf = '';
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n');
    let idx: number;
    while ((idx = buf.indexOf('\n\n')) >= 0) {
      const frame = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      let event = 'message';
      const data: string[] = [];
      for (const line of frame.split('\n')) {
        if (line.startsWith(':')) continue;
        if (line.startsWith('event:')) event = line.slice(6).trim();
        else if (line.startsWith('data:')) data.push(line.slice(5).replace(/^ /, ''));
      }
      if (!data.length) continue;
      try {
        onMessage({ event, data: JSON.parse(data.join('\n')) });
      } catch {
        /* skip a broken frame */
      }
    }
  }
}

export interface AskInput { machineCode?: string; text?: string; audio?: { blob: Blob; mimeType: string } }

/** POST /assist/ask and stream the events. Throws UploadError for 4xx/5xx before the stream starts. */
export async function askStream(input: AskInput, onMessage: (m: SSEMessage) => void, signal?: AbortSignal) {
  const form = new FormData();
  if (input.machineCode) form.append('machine_code', input.machineCode);
  if (input.text !== undefined) form.append('text', input.text);
  if (input.audio) form.append('audio', audioFile(input.audio.blob, input.audio.mimeType));
  const res = await fetch(`${apiBase()}/assist/ask`, {
    method: 'POST',
    headers: { ...(await authHeaders()), Accept: 'text/event-stream' },
    body: form,
    signal,
  });
  if (!res.ok || !res.body) throw await errorFrom(res, 'ask_failed');
  await readSSE(res.body, onMessage);
}

// ---------------------------------------------------------------- technician
export const getMachine = (code: string) => call<MachineRef>(`/assist/machines/${encodeURIComponent(code)}`);
export const machineByQr = (token: string) => call<MachineRef>(`/assist/machines/qr/${encodeURIComponent(token)}`);
export const listQueries = (limit = 20) => call<{ items: QueryListItem[] }>(`/assist/queries?limit=${limit}`);
export const getQuery = (id: string) => call<QueryView>(`/assist/queries/${id}`);
export const sendFeedback = (id: string, outcome: Outcome) => json<QueryView>(`/assist/queries/${id}/feedback`, 'POST', { outcome });
export const escalateQuery = (id: string, note?: string) =>
  json<{ escalation_id: string; assigned_to: Person | null }>(`/assist/queries/${id}/escalate`, 'POST', { note: note || null });

export type SpeechResult = Blob | { tts: 'browser'; lang: string };

/** Server voice (WAV blob), or {tts:"browser"} when both Sarvam and Azure are unavailable. */
export async function fetchSpeech(id: string): Promise<SpeechResult> {
  const res = await fetch(`${apiBase()}/assist/queries/${id}/tts`, { method: 'POST', headers: await authHeaders() });
  if (!res.ok) throw await errorFrom(res, 'tts_failed');
  const type = res.headers.get('content-type') || '';
  if (type.includes('application/json')) return await res.json() as { tts: 'browser'; lang: string };
  return res.blob();
}

export function getSource(s: Pick<Source, 'source_type' | 'source_id' | 'page'>): Promise<SourceDetail> {
  if (s.source_type === 'record') return call<RecordSource>(`/assist/sources/record/${s.source_id}`);
  if (s.source_type === 'log') return call<LogSource>(`/assist/sources/log/${s.source_id}`);
  return call<ManualSource>(`/assist/sources/manual/${s.source_id}${s.page ? `?page=${s.page}` : ''}`);
}

// ---------------------------------------------------------------- expert (phone)
export const expertInbox = (scope: 'open' | 'done' = 'open') => call<{ items: Escalation[] }>(`/expert/escalations?scope=${scope}`);
export const expertCount = () => call<{ mine: number; unassigned: number }>('/expert/escalations/count');
export const expertEscalation = (id: string) => call<EscalationDetail>(`/expert/escalations/${id}`);
export const takeEscalation = (id: string) => json<EscalationDetail>(`/expert/escalations/${id}/take`, 'POST');
export const replyText = (id: string, text: string) => json<EscalationDetail>(`/expert/escalations/${id}/reply-text`, 'POST', { text });

export async function replyVoice(id: string, blob: Blob, mimeType: string): Promise<{ record_id: string }> {
  const form = new FormData();
  form.append('audio', audioFile(blob, mimeType));
  const res = await fetch(`${apiBase()}/expert/escalations/${id}/reply`, { method: 'POST', headers: await authHeaders(), body: form });
  if (!res.ok) throw await errorFrom(res, 'upload_failed');
  return res.json();
}

// ---------------------------------------------------------------- supervisor (web, W2)
export type EscFilter = 'open' | 'answered' | 'closed' | 'all';
export const managerEscalations = (status: EscFilter = 'open') =>
  call<{ items: Escalation[]; counts: { open: number; unassigned: number } }>(`/manager/escalations?status=${status}`);
export const managerEscalationCount = () => call<{ open: number; unassigned: number }>('/manager/escalations/count');
export const managerEscalation = (id: string) => call<EscalationDetail>(`/manager/escalations/${id}`);
export const assignEscalation = (id: string, userId: string) =>
  json<EscalationDetail>(`/manager/escalations/${id}/assign`, 'POST', { user_id: userId });
export const closeEscalation = (id: string, reason: 'not_needed' | 'fixed_by_technician' = 'not_needed') =>
  json<EscalationDetail>(`/manager/escalations/${id}/close`, 'POST', { reason });
export const listExperts = () => call<{ items: Expert[] }>('/manager/experts');
