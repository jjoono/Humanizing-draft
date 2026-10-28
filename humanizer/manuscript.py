"""Turn raw text blocks from a .docx / .pdf / .txt into a sectioned Manuscript."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable

from .models import Manuscript, Paragraph
from .textproc import CAPTION_RE, classify_heading, split_sentences

_LINE_NUMBER = re.compile(r"^\s*\d{1,4}\s*$")
_INLINE_ABSTRACT = re.compile(r"^abstract\s*[:.—\-]\s*\S", re.I)


def build_manuscript(path: str, kind: str, blocks: Iterable[tuple[str, dict[str, Any], bool]]) -> Manuscript:
    """`blocks` yields (text, source, looks_like_heading) in reading order."""
    paragraphs: list[Paragraph] = []
    references: list[str] = []
    section = "front"
    for text, source, heading_hint in blocks:
        text = text.strip()
        if not text or _LINE_NUMBER.match(text):
            continue
        label = classify_heading(text) if (heading_hint or len(text) < 80) else None
        idx = len(paragraphs)
        if label:
            section = label
            paragraphs.append(Paragraph(idx, text, label, is_heading=True, source=source))
            continue
        if heading_hint and len(text.split()) <= 12:
            # Unrecognized heading such as "3.2 Optical simulation": keep the current section.
            paragraphs.append(Paragraph(idx, text, section, is_heading=True, source=source))
            continue
        if section == "references":
            references.append(text)
            paragraphs.append(Paragraph(idx, text, "references", source=source))
            continue
        if section == "backmatter":
            paragraphs.append(Paragraph(idx, text, "backmatter", is_heading=True, source=source))
            continue
        if _INLINE_ABSTRACT.match(text):
            section = "abstract"
        sec = "caption" if CAPTION_RE.match(text) else section
        if sec == "front":
            # Title, author and affiliation lines before the abstract are not prose.
            if len(text.split()) < 25:
                paragraphs.append(Paragraph(idx, text, "front", is_heading=True, source=source))
                continue
            # Without an "Abstract" heading only the first prose paragraph is taken as the
            # abstract; the rest stays unlabelled until a recognized heading appears.
            sec, section = "abstract", "other"
        paragraphs.append(Paragraph(idx, text, sec, sentences=split_sentences(text), source=source))
    return Manuscript(path=path, kind=kind, paragraphs=paragraphs, references=references)


def read_text_file(path: str | Path) -> Manuscript:
    raw = Path(path).read_text(encoding="utf-8")
    blocks = [(b.replace("\n", " "), {"block": i}, False) for i, b in enumerate(re.split(r"\n\s*\n", raw))]
    return build_manuscript(str(path), "text", blocks)


def load_manuscript(path: str | Path) -> Manuscript:
    suffix = Path(path).suffix.lower()
    if suffix == ".docx":
        from .io_docx import read_docx
        return read_docx(path)
    if suffix == ".pdf":
        from .io_pdf import read_pdf
        return read_pdf(path)
    if suffix in (".txt", ".md"):
        return read_text_file(path)
    raise ValueError(f"Unsupported manuscript format: {suffix} (use .docx, .pdf or .txt)")
