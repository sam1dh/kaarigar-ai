/**
 * Two small SVG charts for W3, no chart library.
 * Palette checked with the dataviz validator (light surface): answered #1C7F5A, not answered #BA7F14 —
 * lightness band, chroma ≥ 0.10, CVD ΔE 9.3 (protan), normal-vision ΔE 19.8, contrast ≥ 3:1: all pass.
 * Marks: columns ≤ 24px with a 4px rounded top, 2px surface gap between stacked parts, hairline solid grid,
 * per-column hover/focus tooltip, a legend for the two series, and a table view twin.
 */
import { useEffect, useRef, useState, type KeyboardEvent } from 'react';
import { useTranslation } from 'react-i18next';

export const SERIES = { answered: '#1C7F5A', other: '#BA7F14' } as const;
const GRID = '#E4E8E3';
const INK_MUTED = '#5B6863';

function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [w, setW] = useState(640);
  useEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver(([e]) => setW(Math.max(280, Math.floor(e.contentRect.width))));
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);
  return [ref, w] as const;
}

function niceMax(v: number) {
  if (v <= 4) return 4;
  const pow = 10 ** Math.floor(Math.log10(v));
  const step = [1, 2, 2.5, 5, 10].map((s) => s * pow).find((s) => v / s <= 4) ?? 10 * pow;
  return Math.ceil(v / step) * step;
}

/** SVG path for a bar with only its data end rounded (r=4), square at the baseline. */
function topRounded(x: number, y: number, w: number, h: number, r = 4) {
  const rr = Math.min(r, w / 2, h);
  return `M${x},${y + h}V${y + rr}Q${x},${y} ${x + rr},${y}H${x + w - rr}Q${x + w},${y} ${x + w},${y + rr}V${y + h}Z`;
}
function rightRounded(x: number, y: number, w: number, h: number, r = 4) {
  const rr = Math.min(r, h / 2, w);
  return `M${x},${y}H${x + w - rr}Q${x + w},${y} ${x + w},${y + rr}V${y + h - rr}Q${x + w},${y + h} ${x + w - rr},${y + h}H${x}Z`;
}

export interface DayPoint { day: string; questions: number; answered: number }

export function QuestionsPerDay({ data, lang }: { data: DayPoint[]; lang: string }) {
  const { t } = useTranslation();
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const H = 220, padL = 36, padR = 8, padT = 8, padB = 28;
  const plotW = width - padL - padR, plotH = H - padT - padB;
  const max = niceMax(Math.max(1, ...data.map((d) => d.questions)));
  const band = plotW / Math.max(1, data.length);
  const bw = Math.max(2, Math.min(24, band - 2));
  const y = (v: number) => padT + plotH - (v / max) * plotH;
  const ticks = [0, max / 4, max / 2, (3 * max) / 4, max].filter((v) => Number.isInteger(v));
  const fmtDay = (d: string, long = false) => new Date(`${d}T00:00:00`).toLocaleDateString(lang, long ? { weekday: 'short', day: 'numeric', month: 'short' } : { day: 'numeric', month: 'short' });
  const labelEvery = Math.ceil(data.length / Math.max(1, Math.floor(plotW / 64)));
  const onKey = (e: KeyboardEvent) => {
    if (e.key === 'ArrowRight') setHover((h) => Math.min(data.length - 1, (h ?? -1) + 1));
    if (e.key === 'ArrowLeft') setHover((h) => Math.max(0, (h ?? data.length) - 1));
  };
  const hd = hover !== null ? data[hover] : null;

  return (
    <div ref={ref} className="relative">
      <svg width={width} height={H} role="img" aria-label={t('manage.analytics.perDay.aria')} tabIndex={0} onKeyDown={onKey}
        onBlur={() => setHover(null)} onMouseLeave={() => setHover(null)} className="focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--green)] rounded-lg">
        {ticks.map((v) => (
          <g key={v}>
            <line x1={padL} x2={width - padR} y1={y(v)} y2={y(v)} stroke={GRID} strokeWidth={1} />
            <text x={padL - 8} y={y(v)} dy="0.32em" textAnchor="end" fontSize={11} fill={INK_MUTED} style={{ fontVariantNumeric: 'tabular-nums' }}>{v}</text>
          </g>
        ))}
        {data.map((d, i) => {
          const x = padL + i * band + (band - bw) / 2;
          const other = d.questions - d.answered;
          const yA = y(d.answered), hA = padT + plotH - yA;
          const hO = (other / max) * plotH;
          const gap = d.answered > 0 && other > 0 ? 2 : 0;
          return (
            <g key={d.day} opacity={hover === null || hover === i ? 1 : 0.55}>
              {d.answered > 0 && <path d={other > 0 ? `M${x},${yA}H${x + bw}V${yA + hA}H${x}Z` : topRounded(x, yA, bw, hA)} fill={SERIES.answered} />}
              {other > 0 && <path d={topRounded(x, yA - gap - hO, bw, hO)} fill={SERIES.other} />}
              <rect x={padL + i * band} y={padT} width={band} height={plotH} fill="transparent" onMouseEnter={() => setHover(i)} />
              {i % labelEvery === 0 && <text x={padL + i * band + band / 2} y={H - 8} textAnchor="middle" fontSize={11} fill={INK_MUTED}>{fmtDay(d.day)}</text>}
            </g>
          );
        })}
        <line x1={padL} x2={width - padR} y1={padT + plotH} y2={padT + plotH} stroke="#C9D0C9" strokeWidth={1} />
      </svg>
      {hd && hover !== null && (
        <div role="status" className="pointer-events-none absolute top-0 z-10 min-w-[150px] rounded-xl border border-[var(--line)] bg-[var(--white)] px-3 py-2 text-sm shadow-[0_6px_20px_rgba(28,38,38,0.12)]"
          style={{ left: Math.min(width - 170, Math.max(0, padL + hover * band + band / 2 - 75)) }}>
          <div className="mb-1 text-xs text-[var(--ink-muted)]">{fmtDay(hd.day, true)}</div>
          <div className="flex items-center gap-2"><b className="tabular-nums">{hd.questions}</b><span className="text-[var(--ink-muted)]">{t('manage.analytics.perDay.questions')}</span></div>
          <div className="flex items-center gap-2"><span className="h-0.5 w-3 rounded" style={{ background: SERIES.answered }} /><b className="tabular-nums">{hd.answered}</b><span className="text-[var(--ink-muted)]">{t('manage.analytics.perDay.answered')}</span></div>
          <div className="flex items-center gap-2"><span className="h-0.5 w-3 rounded" style={{ background: SERIES.other }} /><b className="tabular-nums">{hd.questions - hd.answered}</b><span className="text-[var(--ink-muted)]">{t('manage.analytics.perDay.other')}</span></div>
        </div>
      )}
    </div>
  );
}

export function Legend() {
  const { t } = useTranslation();
  return (
    <div className="flex flex-wrap gap-4 text-sm text-[var(--ink-muted)]">
      <span className="flex items-center gap-1.5"><span className="h-3 w-3 rounded-[3px]" style={{ background: SERIES.answered }} />{t('manage.analytics.perDay.answered')}</span>
      <span className="flex items-center gap-1.5"><span className="h-3 w-3 rounded-[3px]" style={{ background: SERIES.other }} />{t('manage.analytics.perDay.other')}</span>
    </div>
  );
}

export interface MachineBar { code: string; name: string | null; questions: number; no_answer: number }

/** Ranked horizontal bars, one series (no legend: the card title names it), value at the bar tip. */
export function MachinesBars({ data }: { data: MachineBar[] }) {
  const { t } = useTranslation();
  const [ref, width] = useWidth<HTMLDivElement>();
  const row = 34, bh = 18, labelW = 76, valueW = 40;
  const max = Math.max(1, ...data.map((d) => d.questions));
  const plotW = Math.max(40, width - labelW - valueW);
  return (
    <div ref={ref}>
      <svg width={width} height={data.length * row} role="img" aria-label={t('manage.analytics.machines.aria')}>
        {data.map((d, i) => {
          const w = Math.max(d.questions > 0 ? 4 : 0, (d.questions / max) * plotW);
          const yy = i * row + (row - bh) / 2;
          return (
            <g key={d.code}>
              <title>{t('manage.analytics.machines.tip', { code: d.code, count: d.questions, noAnswer: d.no_answer })}</title>
              <text x={0} y={i * row + row / 2} dy="0.32em" fontSize={13} fontWeight={600} fill="#1C2626" style={{ fontFamily: 'var(--font-heading)' }}>{d.code}</text>
              {w > 0 && <path d={rightRounded(labelW, yy, w, bh)} fill={SERIES.answered} />}
              <text x={labelW + w + 6} y={i * row + row / 2} dy="0.32em" fontSize={12} fill="#1C2626" style={{ fontVariantNumeric: 'tabular-nums' }}>{d.questions}</text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}
