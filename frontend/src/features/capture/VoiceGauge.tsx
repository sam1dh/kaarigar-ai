/**
 * The one bold element of the design: a hydraulic pressure gauge that is also the record button.
 * Idle: needle at rest, mic in the hub. Recording: needle follows your voice, red stop square, timer.
 */
interface Props {
  recording: boolean;
  level: number;          // 0..1
  seconds: number;
  maxSec: number;
  disabled?: boolean;
  onPress: () => void;
  label: string;          // accessible label, e.g. "Start recording" / "Stop recording"
}

const SWEEP = 240;        // degrees of the dial
const START = -120;       // needle angle at 0

function polar(cx: number, cy: number, r: number, deg: number) {
  const rad = ((deg - 90) * Math.PI) / 180;
  return { x: cx + r * Math.cos(rad), y: cy + r * Math.sin(rad) };
}

function arc(cx: number, cy: number, r: number, from: number, to: number) {
  const a = polar(cx, cy, r, from);
  const b = polar(cx, cy, r, to);
  const large = to - from > 180 ? 1 : 0;
  return `M ${a.x} ${a.y} A ${r} ${r} 0 ${large} 1 ${b.x} ${b.y}`;
}

export function fmt(sec: number) {
  const s = Math.max(0, Math.floor(sec));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

export default function VoiceGauge({ recording, level, seconds, maxSec, disabled, onPress, label }: Props) {
  const cx = 120;
  const cy = 120;
  const needle = START + SWEEP * (recording ? Math.min(1, 0.06 + level * 0.94) : 0.02);
  const progress = Math.min(1, seconds / maxSec);
  const ticks = Array.from({ length: 26 }, (_, i) => i);
  const tip = polar(cx, cy, 78, needle);
  const tail = polar(cx, cy, 16, needle + 180);

  return (
    <button
      type="button"
      onClick={onPress}
      disabled={disabled}
      aria-label={label}
      aria-pressed={recording}
      className="relative mx-auto block rounded-full outline-none transition-transform active:scale-[0.98] disabled:opacity-50 focus-visible:ring-4 focus-visible:ring-[var(--green-tint)]"
      style={{ width: 240, height: 240 }}
    >
      <svg viewBox="0 0 240 240" width="240" height="240" aria-hidden="true">
        {/* bezel */}
        <circle cx={cx} cy={cy} r="116" fill="var(--green-deep)" />
        <circle cx={cx} cy={cy} r="104" fill="var(--surface)" />
        {/* dial ticks */}
        {ticks.map((i) => {
          const deg = START + (SWEEP * i) / 25;
          const major = i % 5 === 0;
          const a = polar(cx, cy, 96, deg);
          const b = polar(cx, cy, major ? 84 : 89, deg);
          return (
            <line key={i} x1={a.x} y1={a.y} x2={b.x} y2={b.y}
              stroke={i >= 21 ? 'var(--alert)' : 'var(--ink-muted)'} strokeWidth={major ? 2.5 : 1.2} strokeLinecap="round" />
          );
        })}
        {/* red zone */}
        <path d={arc(cx, cy, 99, START + SWEEP * 0.84, START + SWEEP)} stroke="var(--alert)" strokeWidth="4" fill="none" opacity="0.55" />
        {/* time used, as a thin arc inside */}
        {recording && (
          <path d={arc(cx, cy, 74, START, START + Math.max(1, SWEEP * progress))}
            stroke="var(--green)" strokeWidth="3" fill="none" strokeLinecap="round" opacity="0.5" />
        )}
        {/* needle */}
        <line x1={tail.x} y1={tail.y} x2={tip.x} y2={tip.y}
          stroke={recording ? 'var(--alert)' : 'var(--ink)'} strokeWidth="4" strokeLinecap="round"
          style={{ transition: 'all 90ms linear' }} />
        <circle cx={cx} cy={cy} r="30" fill={recording ? 'var(--alert)' : 'var(--green-deep)'} />
        {recording ? (
          <rect x={cx - 9} y={cy - 9} width="18" height="18" rx="3" fill="var(--white)" />
        ) : (
          <g fill="none" stroke="var(--white)" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
            <rect x={cx - 6} y={cy - 15} width="12" height="19" rx="6" />
            <path d={`M ${cx - 11} ${cy - 2} a 11 11 0 0 0 22 0`} />
            <line x1={cx} y1={cy + 9} x2={cx} y2={cy + 14} />
          </g>
        )}
        <text x={cx} y={cy + 62} textAnchor="middle" fontSize="20" fontWeight="600"
          fill={recording ? 'var(--alert)' : 'var(--ink-muted)'} style={{ fontFamily: 'var(--font-heading)' }}>
          {fmt(seconds)}
        </text>
        <text x={cx} y={cy + 80} textAnchor="middle" fontSize="11" fill="var(--ink-faint)">
          / {fmt(maxSec)}
        </text>
      </svg>
      {recording && (
        <span className="pointer-events-none absolute inset-0 rounded-full ring-4 ring-[var(--alert)] opacity-30 motion-safe:animate-ping" />
      )}
    </button>
  );
}
