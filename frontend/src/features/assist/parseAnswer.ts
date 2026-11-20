/**
 * Live parser for the answer text while it streams (same line format as the backend's answer_format.py):
 *   SAFETY: … [E1]      1. … [E1][M1]      CHECK: … [M1]
 * Works on partial text: an unfinished "[E" at the end is simply not a ref yet.
 */
import type { AnswerParts, Item } from './assistApi';

const REF_RE = /\[\s*([EMH]\d{1,2}(?:\s*[,;/]\s*[EMH]\d{1,2})*)\s*\]/gi;
const STEP_RE = /^\s*(?:step\s*)?(\d{1,2})\s*[.):-]\s*(.*)$/i;
const SAFETY_RE = /^\s*(?:safety|warning|सुरक्षा)\s*[:：-]\s*(.*)$/i;
const CHECK_RE = /^\s*(?:check|verify)\s*[:：-]\s*(.*)$/i;

function splitRefs(text: string): Item {
  const refs: string[] = [];
  const clean = text.replace(REF_RE, (_m, group: string) => {
    for (const part of group.split(/[,;/]/)) {
      const r = part.trim().toUpperCase();
      if (r && !refs.includes(r)) refs.push(r);
    }
    return ' ';
  });
  return { text: clean.replace(/\s+([.,;:!?।])/g, '$1').replace(/\s+/g, ' ').trim(), refs };
}

export function parseAnswerText(text: string): AnswerParts {
  const parts: AnswerParts = { no_answer: false, safety: [], steps: [], check: null, refs_used: [] };
  let last: Item | null = null;
  const loose: Item[] = [];
  for (const raw of text.split('\n')) {
    const line = raw.replace(/\*\*|__/g, '').replace(/^\s*[-•*·]\s+/, '').trim();
    if (!line) continue;
    let m: RegExpMatchArray | null;
    if ((m = line.match(SAFETY_RE))) {
      const it = splitRefs(m[1]);
      if (it.text) parts.safety.push((last = it));
    } else if ((m = line.match(CHECK_RE))) {
      const it = splitRefs(m[1]);
      if (it.text) parts.check = last = it;
    } else if ((m = line.match(STEP_RE))) {
      const it = splitRefs(m[2]);
      if (it.text) parts.steps.push((last = { ...it, n: parts.steps.length + 1 }));
    } else {
      const it = splitRefs(line);
      if (last) {
        last.text = `${last.text} ${it.text}`.trim();
        it.refs.forEach((r) => last!.refs.includes(r) || last!.refs.push(r));
      } else if (it.text) loose.push(it);
    }
  }
  if (loose.length && !parts.steps.length) {
    parts.steps.push({ n: 1, text: loose.map((l) => l.text).join(' '), refs: [...new Set(loose.flatMap((l) => l.refs))] });
  }
  const seen: string[] = [];
  [...parts.safety, ...parts.steps, ...(parts.check ? [parts.check] : [])].forEach((i) =>
    i.refs.forEach((r) => seen.includes(r) || seen.push(r)),
  );
  parts.refs_used = seen;
  return parts;
}

/** Plain text for the browser's speech engine: no refs, safety first. */
export function speakableText(p: AnswerParts, words: { safety: string; check: string }): string {
  const out: string[] = [];
  p.safety.forEach((s) => out.push(`${words.safety}. ${s.text}`));
  p.steps.forEach((s, i) => out.push(`${s.n ?? i + 1}. ${s.text}`));
  if (p.check) out.push(`${words.check}. ${p.check.text}`);
  return out.join('\n');
}

/** One streamed line -> what to say ('' for nothing). "1. Fit the gauge [E1]" -> "1. Fit the gauge". */
export function speakLine(line: string, words: { safety: string; check: string }): string {
  const clean = line.replace(/\*\*|__/g, '').replace(/^\s*[-•*·]\s+/, '').trim();
  if (!clean || /^no[_ ]answer/i.test(clean)) return '';
  let m: RegExpMatchArray | null;
  if ((m = clean.match(SAFETY_RE))) return `${words.safety} ${splitRefs(m[1]).text}`.trim();
  if ((m = clean.match(CHECK_RE))) return `${words.check} ${splitRefs(m[1]).text}`.trim();
  if ((m = clean.match(STEP_RE))) {
    const body = splitRefs(m[2]).text;
    return body ? `${m[1]}. ${body}` : '';
  }
  return splitRefs(clean).text;
}
