import { useEffect, useRef, useState } from 'react';
import { EndOfSpeech, type VadOptions, type VadState } from './vad';

interface Rec { state: string; level: number; stop: () => void; reset: () => void }

/**
 * Stops the recorder by itself when the person stops talking (see vad.ts).
 * Polls the level every 50 ms (React won't re-render when the level stays exactly the same, e.g. total silence).
 * `onNoSpeech` runs when nobody spoke for 8 s: the recording is thrown away instead of being sent.
 */
export function useAutoStop(rec: Rec, enabled: boolean, onNoSpeech: () => void, opts?: Partial<VadOptions>) {
  const [vad, setVad] = useState<VadState | null>(null);
  const levelRef = useRef(0);
  const recRef = useRef(rec);
  const cbRef = useRef(onNoSpeech);
  levelRef.current = rec.level;
  recRef.current = rec;
  cbRef.current = onNoSpeech;

  useEffect(() => {
    if (!enabled || rec.state !== 'recording') {
      setVad(null);
      return;
    }
    const det = new EndOfSpeech(opts);
    setVad(det.state);
    const id = window.setInterval(() => {
      const before = det.state;
      const st = det.update(levelRef.current, performance.now());
      if (st !== before) setVad(st);
      if (st === 'done') {
        window.clearInterval(id);
        recRef.current.stop();
      } else if (st === 'nospeech') {
        window.clearInterval(id);
        recRef.current.reset();
        cbRef.current();
      }
    }, 50);
    return () => window.clearInterval(id);
  }, [enabled, rec.state]);

  return vad;
}
