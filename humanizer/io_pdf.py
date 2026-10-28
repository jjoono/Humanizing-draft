"""Read .pdf manuscripts and write an annotated copy (highlight annotations + notes)."""
from __future__ import annotations

import re
from pathlib import Path

import pymupdf

from .manuscript import build_manuscript
from .models import AnalysisResult, Manuscript
from .report import comment_text
from .textproc import dehyphenate

COLORS = {"high": (1.0, 0.45, 0.45), "medium": (1.0, 0.9, 0.3), "low": (0.55, 0.85, 1.0)}
_LEADING_LINE_NO = re.compile(r"^\s*\d{1,4}\s+")


def _clean_block(text: str) -> str:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    # Review manuscripts often carry line numbers; strip them when most lines have one.
    if lines and sum(bool(_LEADING_LINE_NO.match(ln)) for ln in lines) >= 0.6 * len(lines):
        lines = [_LEADING_LINE_NO.sub("", ln) for ln in lines]
    return dehyphenate("\n".join(lines))


def _blocks(doc: pymupdf.Document):
    for pno, page in enumerate(doc):
        height = page.rect.height
        for x0, y0, x1, y1, text, _bno, btype in page.get_text("blocks"):
            if btype != 0:
                continue
            clean = _clean_block(text)
            if not clean:
                continue
            # Running headers/footers: short text in the top/bottom 5% of the page.
            if (y1 < 0.05 * height or y0 > 0.95 * height) and len(clean.split()) < 12:
                continue
            short = len(clean.split()) <= 12 and not clean.rstrip().endswith((".", ":", ";"))
            yield clean, {"page": pno, "bbox": [x0, y0, x1, y1]}, short


def read_pdf(path: str | Path) -> Manuscript:
    with pymupdf.open(str(path)) as doc:
        return build_manuscript(str(path), "pdf", list(_blocks(doc)))


def _find_quads(page, text: str, clip):
    hits = page.search_for(text, clip=clip, quads=True)
    if hits:
        return hits
    toks = text.split()
    quads = []
    for i in range(0, len(toks), 5):
        chunk = " ".join(toks[i:i + 5])
        if len(chunk) >= 8:
            quads.extend(page.search_for(chunk, clip=clip, quads=True)[:1])
    return quads


def annotate_pdf(result: AnalysisResult, out_path: str | Path, min_risk: str = "medium") -> int:
    by_index = {p.index: p for p in result.manuscript.paragraphs}
    count = 0
    with pymupdf.open(result.manuscript.path) as doc:
        for f in result.by_risk(min_risk):
            src = by_index[f.para_index].source
            if "page" not in src:
                continue
            page = doc[src["page"]]
            clip = pymupdf.Rect(src["bbox"]) + (-2, -2, 2, 2)
            quads = _find_quads(page, f.text, clip)
            if quads:
                annot = page.add_highlight_annot(quads)
            else:
                annot = page.add_text_annot(clip.tl, "")
            annot.set_colors(stroke=COLORS.get(f.risk, COLORS["low"]))
            annot.set_info(title="Humanizer", content=comment_text(f))
            annot.update()
            count += 1
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        doc.save(str(out_path), garbage=3, deflate=True)
    return count
