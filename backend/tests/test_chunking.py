"""Unit tests for manual chunking (no DB, no PDF files)."""

from app.services import chunking


def _page(page_number: int, text: str) -> dict:
    return {"text": text, "metadata": {"page_number": page_number}}


# ===== footers =====

def test_footer_removed_on_majority_of_pages() -> None:
    pages = [
        _page(1, "Intro paragraph about the pump.\n\nPage 1\nAC-75 Service Manual"),
        _page(2, "More pump details here.\n\nPage 2\nAC-75 Service Manual"),
        _page(3, "Even more pump details.\n\nPage 3\nAC-75 Service Manual"),
    ]
    chunks = chunking.chunk_manual(pages)
    joined = "\n".join(c["text"] for c in chunks)
    assert "Page 1" not in joined
    assert "AC-75 Service Manual" not in joined
    assert "Intro paragraph about the pump." in joined


def test_two_page_doc_keeps_unique_content() -> None:
    # strict majority rule: with 2 pages, a line must appear on BOTH pages to be a footer
    pages = [
        _page(1, "Alpha content line.\n\nPage 1"),
        _page(2, "Beta content line.\n\nPage 2"),
    ]
    joined = "\n".join(c["text"] for c in chunking.chunk_manual(pages))
    assert "Alpha content line." in joined
    assert "Beta content line." in joined


def test_repeated_table_header_survives_footer_removal() -> None:
    # A markdown table continuing across a page break repeats its header row;
    # table lines must never be treated as footers (CL-40 page-2 case).
    # The parser reformats rows to "Problem: X | Cause: Y | Remedy: Z".
    pages = [
        _page(1, "Intro text.\n\n|Problem|Cause|Remedy|\n|---|---|---|\n|Chatter|Worn insert|Replace insert.|"),
        _page(2, "|Problem|Cause|Remedy|\n|Spindle not starting|Interlock open|Realign switch.|"),
    ]
    joined = "\n".join(c["text"] for c in chunking.chunk_manual(pages))
    assert "Chatter | Cause: Worn insert" in joined  # page-1 row parsed
    assert "Spindle not starting | Cause: Interlock open" in joined  # page-2 row parsed
    assert "|---|" not in joined


# ===== headings / sections =====

def test_heading_starts_new_section() -> None:
    pages = [
        _page(1, "# 3 Lubrication\n\nWay oil ISO VG 68 fills the tank.\n\n# 4 Alarms\n\nAlarm 1012 means low lubrication."),
    ]
    chunks = chunking.chunk_manual(pages)
    sections = {c["section"] for c in chunks}
    assert "3 Lubrication" in sections
    assert "4 Alarms" in sections
    # the two sections must not be packed into one chunk
    assert len(chunks) >= 2


# ===== packing =====

def test_paragraph_chunks_respect_word_cap() -> None:
    para = " ".join(f"word{i}" for i in range(120))
    pages = [_page(1, para + "\n\n" + para + "\n\n" + para)]
    chunks = chunking.chunk_manual(pages)
    assert chunks
    for c in chunks:
        assert len(c["text"].split()) <= chunking.WORDS_MAX


def test_table_chunked_in_row_groups() -> None:
    header = "|Code|Meaning|\n|---|---|"
    rows = "\n".join(f"|E-{i:02d}|Alarm {i:02d}|" for i in range(1, 13))
    pages = [_page(1, f"{header}\n{rows}")]
    chunks = chunking.chunk_manual(pages)
    # 12 rows / 5 per chunk -> 3 chunks
    assert len(chunks) == 3


# ===== OCR =====

def test_picture_text_becomes_content_and_is_flagged() -> None:
    pages = [
        _page(
            4,
            "<!-- Start of picture text -->Scanned alarm table E-05 oil overheat."
            "<!-- End of picture text -->",
        )
    ]
    chunks = chunking.chunk_manual(pages)
    assert chunks
    assert "E-05" in chunks[0]["text"]
    assert chunks[0]["meta"].get("ocr") is True


def test_chunk_indexes_are_ordered() -> None:
    pages = [
        _page(1, "# A\n\nAlpha text.\n\n# B\n\nBeta text."),
        _page(2, "# C\n\nGamma text."),
    ]
    chunks = chunking.chunk_manual(pages)
    assert [c["chunk_index"] for c in chunks] == list(range(len(chunks)))
