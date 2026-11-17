"""Markdown → chunks for manuals (paragraphs + tables).

Input: pymupdf4llm.to_markdown(path, page_chunks=True) page dicts.
Output chunks: {text, section, page, chunk_index, meta}.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

# ---- tunables (eval may adjust) --------------------------------------------
WORDS_PER_CHUNK = 220   # pack paragraphs up to ~220 words...
WORDS_MAX = 320         # ...never more than 320
WORDS_OVERLAP = 40      # 40-word overlap between consecutive paragraph chunks
MIN_WORDS = 15          # pieces under 15 words merge into the next chunk
TABLE_ROWS_PER_CHUNK = 5

_BR = re.compile(r"<br\s*/?>", re.IGNORECASE)
_BOLD = re.compile(r"\*\*")
_ITAL = re.compile(r"(?<!\w)_([^_]+)_(?!\w)")
_WS = re.compile(r"[ \t]+")
_PICTURE = re.compile(r"<!--\s*Start of picture text\s*-->(.*?)(?:<!--\s*End of picture text\s*-->|\Z)", re.S)
_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_PAGE_ONLY = re.compile(r"^page #?$", re.IGNORECASE)
# The demo manuals carry a literal footer marker; OCR may also merge it into a
# content line, where the "repeated line" detector can't see it.
_FOOTER_MARK = "fictional manual for demo use only"


@dataclass
class Block:
    kind: str            # 'paragraph' | 'table' | 'heading'
    text: str
    page: int
    section: list[str] = field(default_factory=list)


def _normalize(line: str) -> str:
    """Line shape for the repeated-footer detector: digits → '#', no bold/ws."""
    return _WS.sub(" ", _BOLD.sub("", line)).strip().translate(str.maketrans("0123456789", "##########"))


def _strip_demo_footers(lines: list[str]) -> list[str]:
    """Drop the demo footer marker and lone 'Page N' lines; cut merged footer tails.

    A line whose footer segment starts in its first half is a pure footer line
    and goes away entirely; otherwise the footer tail is truncated off a
    content line. OCR'd single-page docs get the same treatment because
    repetition-based detection needs >= 2 pages.
    """
    out = []
    for ln in lines:
        i = ln.lower().find(_FOOTER_MARK)
        if i == -1:
            if _PAGE_ONLY.match(ln.strip()):
                continue
            out.append(ln)
            continue
        prefix = ln[:i].rstrip(" -—·")
        if len(prefix) <= len(ln) / 2 or not prefix.strip():
            continue  # pure footer line
        out.append(prefix)
    return out


def clean_pages(pages: list[dict]) -> list[dict]:
    """1. Clean each page: <br>, bold markers, footers, OCR picture text."""
    cleaned = []
    for d in pages:
        text = d["text"] or ""
        meta = d.get("metadata") or {}
        page_no = meta.get("page_number", 0)
        ocr = False
        m = _PICTURE.search(text)
        if m:
            ocr = True
            inner = m.group(1)
            text = text[: m.start()] + inner + text[m.end():]
        text = _BR.sub(" ", text)
        text = _BOLD.sub("", text)
        lines = [_WS.sub(" ", ln).strip() for ln in text.splitlines()]
        cleaned.append({"page": page_no, "lines": lines, "ocr": ocr})

    # Footer marker / lone page numbers first (works for single-page and OCR-merged
    # lines), then the generic repeated-line detector.
    for c in cleaned:
        c["lines"] = _strip_demo_footers(c["lines"])

    # Footers: remove lines that repeat on a strict majority of pages ("Page 2" etc).
    # Table lines are excluded: markdown tables repeated across a page break share
    # their header row, which must survive for the row lines to parse.
    if len(cleaned) >= 2:
        counter: Counter[str] = Counter()
        for c in cleaned:
            seen = set()
            for ln in c["lines"]:
                if ln and ln not in seen and not ln.lstrip().startswith("|"):
                    counter[_normalize(ln)] += 1
                    seen.add(ln)
        repeated = {ln for ln, n in counter.items() if n * 2 > len(cleaned)}
        if repeated:
            for c in cleaned:
                c["lines"] = [ln for ln in c["lines"] if ln == "" or _normalize(ln) not in repeated]

    for c in cleaned:
        c["text"] = "\n".join(c["lines"]).strip()
    return cleaned


def split_blocks(cleaned: list[dict]) -> list[Block]:
    """2. Headings / paragraphs / tables, with a section path from headings."""
    blocks: list[Block] = []
    section: list[str] = []
    subs: list[tuple[int, str]] = []  # (level, text) tail under the current level<=2 heading
    for c in cleaned:
        para: list[str] = []
        table: list[str] = []
        page_no = c["page"]

        def flush_para(para=para, table=table, page_no=page_no) -> None:
            if para:
                text = " ".join(para).strip()
                if text:
                    blocks.append(Block("paragraph", text, page_no, list(section)))
                para.clear()

        def flush_table(table=table, page_no=page_no) -> None:
            if table:
                blocks.append(Block("table", "\n".join(table), page_no, list(section)))
                table.clear()

        for ln in c["lines"]:
            if not ln.strip():
                flush_para()
                flush_table()
                continue
            hm = _HEADING.match(ln)
            if hm:
                flush_para()
                flush_table()
                level = len(hm.group(1))
                raw = hm.group(2).strip()
                text = _ITAL.sub("", raw).strip()
                if not text:
                    # a fully-italic heading ('### _6.1 Doing a thing_') must keep
                    # its text — keep the italic content instead of an empty level
                    text = _ITAL.sub(r"\1", raw).strip()
                if level <= 2:
                    section[:] = [text]
                    subs.clear()
                else:
                    while subs and subs[-1][0] >= level:
                        subs.pop()
                    subs.append((level, text))
                    section[:] = section[:1] + [t for _, t in subs]
                blocks.append(Block("heading", text, page_no, list(section)))
            elif ln.lstrip().startswith("|"):
                flush_para()
                table.append(ln.strip())
            else:
                flush_table()
                para.append(ln.strip())
        flush_para()
        flush_table()
    return blocks


def _pack_paragraphs(texts: list[str], pages: list[int]) -> list[tuple[str, int]]:
    """3. Pack paragraphs up to ~220 words (max 320) with 40-word overlap."""
    packed: list[tuple[str, int]] = []
    cur: list[str] = []
    cur_words = 0
    cur_page = pages[0] if pages else 0
    for text, pg in zip(texts, pages, strict=False):
        words = text.split()
        cur_page = min(cur_page, pg) if cur else pg
        # hard-split very long paragraphs
        pieces: list[str] = []
        while len(words) > WORDS_MAX:
            pieces.append(" ".join(words[:WORDS_MAX]))
            words = words[WORDS_MAX - WORDS_OVERLAP :]
        if words:
            pieces.append(" ".join(words))
        for piece in pieces:
            pw = len(piece.split())
            if cur and cur_words + pw > WORDS_PER_CHUNK:
                packed.append((" ".join(cur), cur_page))
                overlap = " ".join(" ".join(cur).split()[-WORDS_OVERLAP:])
                cur = [overlap, piece] if overlap else [piece]
                cur_words = len(" ".join(cur).split())
                cur_page = pg
            else:
                cur.append(piece)
                cur_words += pw
    if cur:
        packed.append((" ".join(cur), cur_page))

    # merge tiny pieces into the next chunk (last one into the previous)
    merged: list[tuple[str, int]] = []
    for text, pg in packed:
        if merged and len(text.split()) < MIN_WORDS:
            prev_text, prev_pg = merged[-1]
            merged[-1] = (f"{prev_text} {text}".strip(), prev_pg)
        else:
            merged.append((text, pg))
    # a trailing tiny chunk merges backwards
    if len(merged) >= 2 and len(merged[-1][0].split()) < MIN_WORDS:
        text, _ = merged.pop()
        prev_text, prev_pg = merged[-1]
        merged[-1] = (f"{prev_text} {text}".strip(), prev_pg)
    return merged


def _parse_table(table_text: str) -> tuple[list[str], list[list[str]]]:
    """Return (headers, data rows) from a markdown table."""
    rows = []
    for ln in table_text.splitlines():
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        rows.append(cells)
    if not rows:
        return [], []
    headers = rows[0]
    data = [r for r in rows[1:] if not all(set(cell) <= set("-: ") and cell for cell in r)]
    data = [r for r in data if any(r)]
    return headers, data


def _table_chunks(table_text: str, section: str, page: int) -> list[tuple[str, int]]:
    """4. One chunk per group of up to 5 data rows; rows become 'Header: value' lines."""
    headers, data = _parse_table(table_text)
    out = []
    for start in range(0, len(data), TABLE_ROWS_PER_CHUNK):
        lines = []
        for row in data[start : start + TABLE_ROWS_PER_CHUNK]:
            parts = []
            for i, cell in enumerate(row):
                h = headers[i] if i < len(headers) else f"Col {i + 1}"
                if cell:
                    parts.append(f"{h}: {cell}")
            if parts:
                lines.append(" | ".join(parts))
        if lines:
            prefix = f"{section}\n" if section else ""
            out.append((prefix + "\n".join(lines), page))
    return out


def chunk_manual(pages: list[dict]) -> list[dict]:
    """Full pipeline: clean → blocks → chunks.

    Paragraph packs live inside one section path (flushed at every heading and
    table boundary — OCR'd re-appearances of a section on later pages become
    their own chunks instead of being pulled into the page-1 intro).
    """
    cleaned = clean_pages(pages)
    ocr_pages = {c["page"] for c in cleaned if c["ocr"]}
    blocks = split_blocks(cleaned)

    chunks: list[dict] = []

    def emit(text: str, section: str, page: int) -> None:
        meta = {"ocr": True} if page in ocr_pages else {}
        chunks.append({"text": text, "section": section, "page": page, "meta": meta})

    para_texts: list[str] = []
    para_pages: list[int] = []
    para_section = ""

    def flush_paras() -> None:
        nonlocal para_texts, para_pages, para_section
        if para_texts:
            sec = para_section
            for text, pg in _pack_paragraphs(para_texts, para_pages):
                emit(text, sec, pg)
            para_texts, para_pages, para_section = [], [], ""

    for b in blocks:
        if b.kind == "heading":
            flush_paras()
        elif b.kind == "paragraph":
            sec = " > ".join(b.section)
            if para_texts and sec != para_section:
                flush_paras()
            para_texts.append(b.text)
            para_pages.append(b.page)
            para_section = sec
        elif b.kind == "table":
            flush_paras()
            sec = " > ".join(b.section)
            for text, pg in _table_chunks(b.text, sec, b.page):
                emit(text, sec, pg)
    flush_paras()

    for i, c in enumerate(chunks):
        c["chunk_index"] = i
    return chunks


def chunks_from_pdf(path: str) -> tuple[list[dict], list[int]]:
    """Convenience: pymupdf4llm → cleaned chunks + the page list for scanned detection."""
    import pymupdf4llm

    pages = pymupdf4llm.to_markdown(path, page_chunks=True)
    return chunk_manual(pages), [d.get("metadata", {}).get("page_number", 0) for d in pages]
