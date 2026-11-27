"""Turn PDFs into text chunks for the vector store. No model call here, so this file has no gateway dependency.

Rules:
- A chunk never crosses a page, so every chunk has one page number for citations (split="page").
- Size and overlap are in characters. They are options, so the rebuild script can try other values.
- split="section" is allowed by model_settings but is not built; asking for it is an error, not a silent fallback.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
LATEST_ANNUAL_REPORTS = 3      # tier 2
LATEST_PRESENTATIONS = 5       # tier 3 (plan said 4 to 6)

_NAME = re.compile(r"^(Transcript|Annual_Report|PPT)(?:_([A-Za-z]{3}))?_(\d{4})(?:_\d+)?\.pdf$", re.I)
_TYPES = {"transcript": "transcript", "annual_report": "annual_report", "ppt": "presentation"}


@dataclass
class Chunk:
    text: str
    page: int      # 1-based page number in the PDF
    n: int         # chunk number within the page, from 0


def chunk_text(text: str, size: int, overlap: int) -> list[str]:
    """Cut text into pieces of at most `size` characters. Each piece starts `overlap` characters before the
    end of the previous one, moved to a word start where possible. Breaks at a space when one is near the end."""
    if size < 1 or overlap < 0 or overlap >= size:
        raise ValueError("size must be at least 1 and overlap must be smaller than size")
    text = re.sub(r"[ \t]+", " ", text).strip()
    if not text:
        return []
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            space = text.rfind(" ", start + size // 2, end)
            if space != -1:
                end = space
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= len(text):
            break
        nxt = end - overlap
        if overlap:
            sp = text.find(" ", nxt, end)                  # begin on a word start
            nxt = sp + 1 if sp != -1 else nxt
        start = nxt if nxt > start else end                # always move forward
    return chunks


def chunk_pages(pages: list[str], size: int, overlap: int, split: str = "page") -> tuple[list[Chunk], dict]:
    if split != "page":
        raise ValueError(f"split '{split}' is not built yet; only 'page' works")
    out: list[Chunk] = []
    empty = 0
    for number, text in enumerate(pages, 1):
        pieces = chunk_text(text or "", size, overlap)
        if not pieces:
            empty += 1
        out.extend(Chunk(piece, number, i) for i, piece in enumerate(pieces))
    return out, {"pages": len(pages), "empty_pages": empty, "chunks": len(out)}


def parse_document_name(name: str):
    """(doc_type, year, month) from a downloaded file name, or None if it is not a PDF we index."""
    m = _NAME.match(name)
    if not m:
        return None
    kind, month, year = m.groups()
    kind = kind.lower()
    return _TYPES[kind], int(year), month.capitalize() if month else ""


def _order(item):
    _, year, month = item[1]
    return (year, MONTHS.index(month) if month in MONTHS else -1, item[0].name)


def select_documents(folder: Path, tiers=(1, 2, 3), annual_reports: int = LATEST_ANNUAL_REPORTS,
                     presentations: int = LATEST_PRESENTATIONS) -> list[Path]:
    """PDFs in one stock folder for the chosen tiers: 1 all transcripts, 2 latest annual reports, 3 latest presentations."""
    found = {"transcript": [], "annual_report": [], "presentation": []}
    for f in Path(folder).glob("*.pdf"):
        info = parse_document_name(f.name)
        if info:
            found[info[0]].append((f, info))
    chosen: list[Path] = []
    if 1 in tiers:
        chosen += [f for f, _ in sorted(found["transcript"], key=_order)]
    if 2 in tiers:
        chosen += [f for f, _ in sorted(found["annual_report"], key=_order)[-annual_reports:]]
    if 3 in tiers:
        chosen += [f for f, _ in sorted(found["presentation"], key=_order)[-presentations:]]
    return chosen


def read_pdf_pages(path: Path) -> list[str]:
    """Text of each page. Imported here so the chunker tests do not need PyMuPDF."""
    import pymupdf
    with pymupdf.open(str(path)) as doc:
        return [page.get_text("text") for page in doc]


def count_pages(path: Path) -> int:
    """Page count without reading the text (fast)."""
    import pymupdf
    with pymupdf.open(str(path)) as doc:
        return doc.page_count
