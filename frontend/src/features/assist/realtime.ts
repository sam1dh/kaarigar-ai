/**
 * Live updates without polling: when a row in `table` changes (Supabase Realtime, RLS-filtered to your plant),
 * the given React Query keys are refetched. The payload itself is ignored on purpose: the API stays the
 * single source of truth, Realtime is only the "something changed" bell.
 * 0004 adds `escalations` and `repair_records` to the supabase_realtime publication.
 */
import { useQueryClient, type QueryKey } from '@tanstack/react-query';
import { useEffect, useRef } from 'react';
import { supabase } from '../../lib/supabase';

let counter = 0;

export function useLiveRefresh(table: 'escalations' | 'repair_records', keys: QueryKey[], enabled = true) {
  const qc = useQueryClient();
  const keysRef = useRef(keys);
  keysRef.current = keys;

  useEffect(() => {
    if (!enabled) return;
    let timer: number | undefined;
    const channel = supabase
      .channel(`live-${table}-${++counter}`)
      .on('postgres_changes', { event: '*', schema: 'public', table }, () => {
        // several rows can change at once (trigger + update): refetch once
        window.clearTimeout(timer);
        timer = window.setTimeout(() => keysRef.current.forEach((k) => qc.invalidateQueries({ queryKey: k })), 300);
      })
      .subscribe();
    return () => {
      window.clearTimeout(timer);
      supabase.removeChannel(channel);
    };
  }, [table, enabled, qc]);
}
