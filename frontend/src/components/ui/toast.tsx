/** Minimal toast: no library needed in Phase 0 ("Coming soon" stubs etc.). */
import { useEffect, useState } from "react";

interface ToastState {
  id: number;
  message: string;
}

let emit: ((t: ToastState | null) => void) | null = null;

export function toast(message: string): void {
  emit?.({ id: Date.now(), message });
}

export function ToastViewport() {
  const [state, setState] = useState<ToastState | null>(null);

  useEffect(() => {
    emit = setState;
    return () => {
      emit = null;
    };
  }, []);

  useEffect(() => {
    if (!state) return;
    const timer = window.setTimeout(() => setState(null), 2400);
    return () => window.clearTimeout(timer);
  }, [state]);

  if (!state) return null;
  return (
    <div
      role="status"
      className="fixed bottom-6 left-1/2 z-50 -translate-x-1/2 rounded-full bg-ink px-5 py-3 text-sm font-medium text-white shadow-lg"
    >
      {state.message}
    </div>
  );
}
