import { useCallback, useEffect, useReducer, useRef } from 'react';
import { errorCode } from '../capture/captureApi';
import {
  askStream, type AnswerParts, type AskInput, type MachineRef, type QueryStatus, type Source, type SSEMessage, type Stage,
} from './assistApi';

export interface AskState {
  phase: 'idle' | 'streaming' | 'done' | 'error';
  stage: Stage | null;
  queryId: string | null;
  machine: MachineRef | null;
  question: { original: string; en: string } | null;
  sources: Source[];
  text: string;                       // streamed answer so far
  parts: AnswerParts | null;          // final, checked answer from `done`
  status: QueryStatus | null;
  confidence: number | null;
  suggestEscalate: boolean;
  error: { code: string; message?: string } | null;
}

const initial: AskState = {
  phase: 'idle', stage: null, queryId: null, machine: null, question: null, sources: [], text: '', parts: null,
  status: null, confidence: null, suggestEscalate: false, error: null,
};

type Action = { type: 'start' } | { type: 'msg'; m: SSEMessage } | { type: 'fail'; code: string; message?: string } | { type: 'reset' };

function reducer(s: AskState, a: Action): AskState {
  switch (a.type) {
    case 'reset':
      return initial;
    case 'start':
      return { ...initial, phase: 'streaming', stage: 'queued' };
    case 'fail':
      return { ...s, phase: 'error', error: { code: a.code, message: a.message } };
    case 'msg': {
      const { event, data } = a.m;
      switch (event) {
        case 'meta':
          return { ...s, queryId: data.query_id, machine: data.machine ?? null };
        case 'stage':
          return { ...s, stage: data.stage };
        case 'question':
          return { ...s, question: { original: data.original, en: data.en } };
        case 'sources':
          return { ...s, sources: data.sources ?? [] };
        case 'delta':
          return { ...s, text: s.text + (data.text ?? '') };
        case 'done':
          return {
            ...s, phase: 'done', stage: null, queryId: data.query_id ?? s.queryId, parts: data.parts, status: data.status,
            confidence: data.confidence ?? null, suggestEscalate: !!data.suggest_escalate,
          };
        case 'error':
          return { ...s, phase: 'error', stage: null, queryId: data.query_id ?? s.queryId, error: { code: data.code, message: data.message } };
        default:
          return s;
      }
    }
  }
}

/** Runs one question against /assist/ask and keeps the streamed state. Leaving the screen cancels it. */
export function useAsk() {
  const [state, dispatch] = useReducer(reducer, initial);
  const abortRef = useRef<AbortController | null>(null);

  const cancel = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
  }, []);

  useEffect(() => cancel, [cancel]);

  const ask = useCallback(async (input: AskInput) => {
    cancel();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    dispatch({ type: 'start' });
    let finished = false;
    try {
      await askStream(input, (m) => {
        if (m.event === 'done' || m.event === 'error') finished = true;
        dispatch({ type: 'msg', m });
      }, ctrl.signal);
      if (!finished && !ctrl.signal.aborted) dispatch({ type: 'fail', code: 'stream_cut' });
    } catch (e) {
      if (ctrl.signal.aborted) return;
      dispatch({ type: 'fail', code: errorCode(e) === 'network' ? 'network' : errorCode(e), message: (e as Error)?.message });
    }
  }, [cancel]);

  const reset = useCallback(() => {
    cancel();
    dispatch({ type: 'reset' });
  }, [cancel]);

  return { state, ask, cancel, reset };
}
