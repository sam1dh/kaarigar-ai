/**
 * Voice activity detection on the phone: "send when I stop talking".
 *
 * Works on the 0..1 voice level the recorder already measures for the gauge needle (no extra library, no model
 * download). It adapts to the room: the first 300 ms set the noise floor, so a loud shop floor raises the
 * thresholds instead of looking like endless speech.
 *
 *   calibrating -> waiting -> speaking -> (silence for 1.1 s after ≥ 0.6 s of speech) -> done
 *   a cough or a bang (loud but < 0.6 s, then quiet) -> back to waiting
 *   waiting for 8 s without speech -> nospeech
 *
 * The tap-to-stop button always still works; VAD only saves the second tap.
 */
export type VadState = 'calibrating' | 'waiting' | 'speaking' | 'done' | 'nospeech';

export interface VadOptions {
  calibrateMs: number;   // measure the room first
  startMs: number;       // loud for this long = speech started
  minSpeechMs: number;   // at least this much voice before we may stop
  silenceMs: number;     // quiet for this long after speech = finished
  noSpeechMs: number;    // give up if nobody speaks
  startFactor: number;   // start threshold = noise floor × this
  stopFactor: number;    // stop threshold  = noise floor × this
  minStart: number;
  minStop: number;
  maxFloor: number;      // someone talking during calibration must not make the floor huge
}

export const DEFAULT_VAD: VadOptions = {
  calibrateMs: 300, startMs: 150, minSpeechMs: 600, silenceMs: 1100, noSpeechMs: 8000,
  startFactor: 2.2, stopFactor: 1.5, minStart: 0.08, minStop: 0.05, maxFloor: 0.15,
};

export class EndOfSpeech {
  private opts: VadOptions;
  private t0: number | null = null;
  private samples: number[] = [];
  private floor = 0;
  private loudSince: number | null = null;
  private quietSince: number | null = null;
  private lastT: number | null = null;
  private waitSince = 0;
  private voicedMs = 0;
  state: VadState = 'calibrating';

  constructor(opts: Partial<VadOptions> = {}) {
    this.opts = { ...DEFAULT_VAD, ...opts };
  }

  get thresholds() {
    const o = this.opts;
    return { start: Math.max(o.minStart, this.floor * o.startFactor), stop: Math.max(o.minStop, this.floor * o.stopFactor) };
  }

  /** Feed one level reading (0..1) with a timestamp in ms. Returns the new state. */
  update(level: number, now: number): VadState {
    const o = this.opts;
    if (this.state === 'done' || this.state === 'nospeech') return this.state;
    if (this.t0 === null) this.t0 = now;
    const dt = this.lastT === null ? 0 : Math.max(0, now - this.lastT);
    this.lastT = now;

    if (this.state === 'calibrating') {
      this.samples.push(level);
      if (now - this.t0 < o.calibrateMs) return this.state;
      const sorted = [...this.samples].sort((a, b) => a - b);
      this.floor = Math.min(o.maxFloor, sorted[Math.floor(sorted.length / 2)] ?? 0);
      this.state = 'waiting';
      this.waitSince = this.t0;
    }
    const { start, stop } = this.thresholds;

    if (this.state === 'waiting') {
      if (level > start) {
        this.loudSince ??= now;
        if (now - this.loudSince >= o.startMs) {
          this.state = 'speaking';
          this.voicedMs = now - this.loudSince;
          this.quietSince = null;
        }
      } else {
        this.loudSince = null;
        if (now - this.waitSince >= o.noSpeechMs) this.state = 'nospeech';
      }
      return this.state;
    }

    // speaking
    if (level > stop) {
      this.voicedMs += dt;
      this.quietSince = null;
    } else {
      this.quietSince ??= now;
      if (now - this.quietSince >= o.silenceMs) {
        if (this.voicedMs >= o.minSpeechMs) this.state = 'done';
        else {                                  // just a cough or a bang: keep listening
          this.state = 'waiting';
          this.loudSince = null;
          this.voicedMs = 0;
          this.waitSince = now;
        }
      }
    }
    return this.state;
  }
}
