"""The answer format, shared by the prompt, the stream and the app.

The writer streams plain text in the technician's language, one item per line:

    SAFETY: Lower the ram onto safety blocks first. [E1]
    1. Fit the test gauge on the pump outlet. [E1]
    2. Set the relief valve to 210 bar and tighten the lock nut. [E1][M1]
    CHECK: Pressure should reach 210 bar within a minute. [M1]

or exactly `NO_ANSWER` when the sources don't answer the question.
Refs: E = expert repair record, M = OEM manual, H = machine history (breakdown log).
The app turns [E1] into a tappable source chip. Unknown refs are removed before saving.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

LABEL_ORDER = ("E", "M", "H")
REF_RE = re.compile(r"\[\s*([EMH]\d{1,2}(?:\s*[,;/]\s*[EMH]\d{1,2})*)\s*\]", re.IGNORECASE)
STEP_RE = re.compile(r"^\s*(?:step\s*)?(\d{1,2})\s*[.):\-]\s*(.*)$", re.IGNORECASE)
SAFETY_RE = re.compile(r"^\s*(?:safety|warning|सुरक्षा)\s*[:：\-]\s*(.*)$", re.IGNORECASE)
CHECK_RE = re.compile(r"^\s*(?:check|verify)\s*[:：\-]\s*(.*)$", re.IGNORECASE)
NO_ANSWER = "NO_ANSWER"


# ---------------------------------------------------------------------------- sources

def build_sources(results: list[dict], context_k: int) -> list[dict]:
    """Take the top `context_k` search results and give each a ref (E1, E2, M1, H1 …) in rank order."""
    counters = {k: 0 for k in LABEL_ORDER}
    out = []
    for r in results[:context_k]:
        label = (r.get("label") or "M").upper()
        if label not in counters:
            label = "M"
        counters[label] += 1
        out.append({
            "ref": f"{label}{counters[label]}",
            "label": label,
            "source_type": r.get("source_type"),
            "source_id": r.get("source_id"),
            "chunk_id": r.get("chunk_id"),
            "title": r.get("title") or "",
            "page": r.get("page"),
            "same_machine": bool(r.get("same_machine")),
            "seed_key": (r.get("meta") or {}).get("seed_key"),
            "snippet": _snippet(r.get("text") or "", 180),
            "_text": r.get("text") or "",           # prompt only; removed before saving / sending
        })
    return out


def public_sources(sources: list[dict]) -> list[dict]:
    return [{k: v for k, v in s.items() if not k.startswith("_")} for s in sources]


def _snippet(text: str, n: int) -> str:
    t = " ".join(text.split())
    return t if len(t) <= n else t[: n - 1].rsplit(" ", 1)[0] + "…"


# ---------------------------------------------------------------------------- parsing

@dataclass
class ParsedAnswer:
    no_answer: bool = False
    safety: list[dict] = field(default_factory=list)   # [{text, refs}]
    steps: list[dict] = field(default_factory=list)    # [{n, text, refs}]
    check: dict | None = None                          # {text, refs}
    refs_used: list[str] = field(default_factory=list)
    dropped_refs: list[str] = field(default_factory=list)

    @property
    def cited_steps(self) -> int:
        return sum(1 for s in self.steps if s["refs"])

    def as_dict(self) -> dict:
        return {"no_answer": self.no_answer, "safety": self.safety, "steps": self.steps, "check": self.check,
                "refs_used": self.refs_used}


def _clean_line(line: str) -> str:
    line = line.replace("**", "").replace("__", "").strip()
    line = re.sub(r"^[\-•*·]\s+", "", line)
    return line.strip()


def _split_refs(text: str, valid: set[str] | None, dropped: list[str]) -> tuple[str, list[str]]:
    refs: list[str] = []

    def repl(m: re.Match) -> str:
        for part in re.split(r"[,;/]", m.group(1)):
            ref = part.strip().upper()
            if not ref:
                continue
            if valid is None or ref in valid:
                if ref not in refs:
                    refs.append(ref)
            elif ref not in dropped:
                dropped.append(ref)
        return " "

    clean = REF_RE.sub(repl, text)
    clean = re.sub(r"\s+([.,;:!?।])", r"\1", " ".join(clean.split()))
    return clean.strip(), refs


def is_no_answer(text: str) -> bool:
    t = text.strip().strip("`*\"' ").upper().replace(" ", "_")
    return t.startswith(NO_ANSWER)


def parse_answer(text: str, valid_refs: set[str] | None = None) -> ParsedAnswer:
    """Parse the writer's text. With `valid_refs`, refs not in the set are dropped (and reported)."""
    p = ParsedAnswer()
    if is_no_answer(text):
        p.no_answer = True
        return p
    loose: list[tuple[str, list[str]]] = []
    last: dict | None = None
    for raw in text.splitlines():
        line = _clean_line(raw)
        if not line:
            continue
        if m := SAFETY_RE.match(line):
            body, refs = _split_refs(m.group(1), valid_refs, p.dropped_refs)
            if body:
                last = {"text": body, "refs": refs}
                p.safety.append(last)
            continue
        if m := CHECK_RE.match(line):
            body, refs = _split_refs(m.group(1), valid_refs, p.dropped_refs)
            if body:
                p.check = last = {"text": body, "refs": refs}
            continue
        if m := STEP_RE.match(line):
            body, refs = _split_refs(m.group(2), valid_refs, p.dropped_refs)
            if body:
                last = {"n": len(p.steps) + 1, "text": body, "refs": refs}
                p.steps.append(last)
            continue
        # A wrapped line: belongs to the previous item. Otherwise keep it as a loose sentence.
        body, refs = _split_refs(line, valid_refs, p.dropped_refs)
        if not body:
            if last is not None:
                last["refs"] += [r for r in refs if r not in last["refs"]]
            continue
        if last is not None:
            last["text"] = f"{last['text']} {body}".strip()
            last["refs"] += [r for r in refs if r not in last["refs"]]
        else:
            loose.append((body, refs))
    if loose and not p.steps:
        # The writer ignored the format: treat the text as one step so nothing is lost.
        body = " ".join(b for b, _ in loose)
        refs_flat = list(dict.fromkeys(r for _, refs in loose for r in refs))
        p.steps.append({"n": 1, "text": body, "refs": refs_flat})
    seen: list[str] = []
    for item in [*p.safety, *p.steps, *([p.check] if p.check else [])]:
        for r in item["refs"]:
            if r not in seen:
                seen.append(r)
    p.refs_used = seen
    if not p.steps and not p.safety:
        p.no_answer = True
    return p


def render_answer(p: ParsedAnswer, *, with_refs: bool = True) -> str:
    """Back to text (refs only from the valid set). Used for saving and for English translation."""
    def item(prefix: str, it: dict) -> str:
        refs = "".join(f"[{r}]" for r in it["refs"]) if with_refs else ""
        return f"{prefix}{it['text']}{(' ' + refs) if refs else ''}"

    if p.no_answer:
        return NO_ANSWER
    lines = [item("SAFETY: ", s) for s in p.safety]
    lines += [item(f"{s['n']}. ", s) for s in p.steps]
    if p.check:
        lines.append(item("CHECK: ", p.check))
    return "\n".join(lines)


def speakable(p: ParsedAnswer, *, safety_word: str = "Safety", check_word: str = "Check") -> str:
    """Text for text-to-speech: no refs, no symbols."""
    parts = [f"{safety_word}. {s['text']}" for s in p.safety]
    parts += [f"{s['n']}. {s['text']}" for s in p.steps]
    if p.check:
        parts.append(f"{check_word}. {p.check['text']}")
    return "\n".join(parts)


def confidence(p: ParsedAnswer, sources: list[dict], search_conf: float | None) -> float:
    """0..1. Grounded, fully cited answers that use an expert record from the same machine score highest.

    If Phase 1's reranker gave a confidence, the result can't be more than 0.25 above it.
    """
    if p.no_answer or not p.steps:
        return 0.0
    ratio = p.cited_steps / len(p.steps)
    by_ref = {s["ref"]: s for s in sources}
    used = [by_ref[r] for r in p.refs_used if r in by_ref]
    bonus = 0.0
    if any(s["label"] == "E" and s.get("same_machine") for s in used):
        bonus = 0.15
    elif any(s["label"] in ("E", "M") for s in used):
        bonus = 0.08
    c = 0.2 + 0.6 * ratio + bonus
    if search_conf is not None:
        c = min(c, search_conf + 0.25)
    return round(max(0.0, min(0.95, c)), 2)


# ---------------------------------------------------------------------------- stream gate

class NoAnswerGate:
    """Holds back the first characters of the stream until we know it isn't `NO_ANSWER`.

    feed(chunk) returns the text that is safe to show now ('' while undecided or for NO_ANSWER).
    """

    def __init__(self) -> None:
        self.buf = ""
        self.decided = False
        self.no_answer = False

    def feed(self, chunk: str) -> str:
        if self.decided:
            return "" if self.no_answer else chunk
        self.buf += chunk
        probe = self.buf.lstrip().lstrip("`*\"' ").upper().replace(" ", "_")
        if not probe:
            return ""
        if probe.startswith(NO_ANSWER):
            self.decided, self.no_answer = True, True
            return ""
        if NO_ANSWER.startswith(probe):
            return ""                     # could still become NO_ANSWER: keep waiting
        self.decided = True
        out, self.buf = self.buf.lstrip(), ""
        return out

    def flush(self) -> str:
        """End of stream: release anything still held (a short answer like "NO")."""
        if self.decided:
            return ""
        self.decided = True
        if is_no_answer(self.buf):
            self.no_answer = True
            return ""
        out, self.buf = self.buf.lstrip(), ""
        return out
