"""Turn downloaded XML/PDF files into a sectioned prose corpus (RULES.md C5)."""
from __future__ import annotations

import hashlib
import json
import logging
import re
import unicodedata
from pathlib import Path

from lxml import etree

from ..manuscript import build_manuscript
from ..textproc import classify_heading, dehyphenate, normalize_citations

log = logging.getLogger(__name__)
PROSE_SECTIONS = {"abstract", "introduction", "methods", "results", "discussion", "conclusion", "caption", "other"}
_SEC_TYPE = {"intro": "introduction", "methods": "methods", "materials|methods": "methods", "results": "results",
             "discussion": "discussion", "results|discussion": "results", "conclusions": "conclusion"}
_SUPER_CIT = re.compile(r"^[\d,–\-\s]+$")


def _clean_para(text: str) -> str | None:
    text = unicodedata.normalize("NFKC", text)  # ligatures such as "ﬁ" -> "fi"
    text = normalize_citations(re.sub(r"\s+", " ", text)).strip()
    text = re.sub(r"(<CIT>\s*){2,}", "<CIT> ", text)
    n_words = len(text.split())
    if n_words < 20:
        return None
    letters = sum(ch.isalpha() for ch in text)
    if letters / max(len(text), 1) < 0.6:
        return None  # equations, tables, garbage
    return text


# --- JATS XML (Europe PMC) ---------------------------------------------------

def _xml_text(el) -> str:
    el = etree.fromstring(etree.tostring(el))  # work on a copy
    for x in list(el.iter("xref")):
        if x.get("ref-type") == "bibr":
            for c in list(x):
                x.remove(c)
            x.text = "[0]"
    for tag in ("disp-formula", "inline-formula", "table-wrap", "fig", "tex-math"):
        for x in list(el.iter(tag)):
            parent, prev, tail = x.getparent(), x.getprevious(), x.tail or ""
            if parent is None:
                continue
            parent.remove(x)
            if prev is not None:
                prev.tail = (prev.tail or "") + tail
            else:
                parent.text = (parent.text or "") + tail
    return "".join(el.itertext())


def _sec_label(sec, inherited: str) -> str:
    st = (sec.get("sec-type") or "").lower()
    if st in _SEC_TYPE:
        return _SEC_TYPE[st]
    title = sec.find("title")
    label = classify_heading("".join(title.itertext())) if title is not None else None
    return label or inherited


def parse_jats(data: bytes) -> list[dict]:
    root = etree.fromstring(data, parser=etree.XMLParser(recover=True, huge_tree=True))
    sections: dict[str, list[str]] = {}

    def add(label: str, text: str) -> None:
        if label in PROSE_SECTIONS and (t := _clean_para(text)):
            sections.setdefault(label, []).append(t)

    for ab in root.iter("abstract"):
        if ab.get("abstract-type") in (None, "", "author"):
            for p in ab.iter("p"):
                add("abstract", _xml_text(p))
            break
    body = root.find(".//body")
    if body is not None:
        def walk(node, label):
            for child in node:
                if child.tag == "sec":
                    walk(child, _sec_label(child, label))
                elif child.tag == "p":
                    add(label, _xml_text(child))
        walk(body, "other")
    for cap in root.iter("caption"):
        for p in cap.iter("p"):
            add("caption", _xml_text(p))
    return [{"section": k, "paragraphs": v} for k, v in sections.items()]


# --- PDF ---------------------------------------------------------------------

def _pdf_blocks(path: Path):
    import pymupdf

    with pymupdf.open(str(path)) as doc:
        for pno, page in enumerate(doc):
            for block in page.get_text("dict")["blocks"]:
                if block.get("type") != 0:
                    continue
                lines, sizes = [], []
                for line in block["lines"]:
                    parts = []
                    for span in line["spans"]:
                        t = span["text"]
                        if span["flags"] & 1 and _SUPER_CIT.match(t.strip() or "x"):
                            parts.append(" [0]")  # superscript citation
                        else:
                            parts.append(t)
                            sizes.append(span["size"])
                    lines.append("".join(parts))
                # A heading often shares a block with the paragraph that follows it.
                if len(lines) > 1 and classify_heading(lines[0]):
                    yield lines[0].strip(), {"page": pno}, True
                    lines = lines[1:]
                text = dehyphenate("\n".join(lines))
                if text:
                    short = len(text.split()) <= 12 and not text.endswith((".", ":", ";"))
                    yield text, {"page": pno}, short


def parse_pdf(path: Path) -> list[dict]:
    ms = build_manuscript(str(path), "pdf", _pdf_blocks(path))
    sections: dict[str, list[str]] = {}
    for p in ms.body():
        if p.section in PROSE_SECTIONS and (t := _clean_para(p.text)):
            sections.setdefault(p.section, []).append(t)
    return [{"section": k, "paragraphs": v} for k, v in sections.items()]


# --- driver ------------------------------------------------------------------

def is_holdout(doc_id: str, fraction: float) -> bool:
    """Deterministic split (rule E1)."""
    h = int(hashlib.sha1(doc_id.encode()).hexdigest()[:8], 16)
    return (h % 1000) < fraction * 1000


def extract_all(candidates: str | Path, raw_dir: str | Path, out_train: str | Path, out_test: str | Path,
                holdout: float = 0.1) -> dict[str, int]:
    raw = Path(raw_dir)
    meta = {}
    with open(candidates, encoding="utf-8") as fh:
        for line in fh:
            r = json.loads(line)
            meta[r["id"]] = {k: r.get(k) for k in ("doi", "title", "year", "venue", "cited_by_count",
                                                   "author_countries", "license", "priority", "domains")}
    stats = {"train": 0, "test": 0, "empty": 0, "failed": 0}
    Path(out_train).parent.mkdir(parents=True, exist_ok=True)
    with open(out_train, "w", encoding="utf-8") as ftr, open(out_test, "w", encoding="utf-8") as fte:
        for wid, m in meta.items():
            src = next((raw / f"{wid}.{ext}" for ext in ("xml", "pdf") if (raw / f"{wid}.{ext}").exists()), None)
            if src is None:
                continue
            try:
                sections = parse_jats(src.read_bytes()) if src.suffix == ".xml" else parse_pdf(src)
            except Exception as e:  # noqa: BLE001 - one bad file must not stop the run
                log.warning("extract failed for %s: %s", src.name, e)
                stats["failed"] += 1
                continue
            if sum(len(s["paragraphs"]) for s in sections) < 3:
                stats["empty"] += 1
                continue
            doc = {"id": wid, "meta": m, "source": src.suffix[1:], "sections": sections}
            split = "test" if is_holdout(wid, holdout) else "train"
            (fte if split == "test" else ftr).write(json.dumps(doc, ensure_ascii=False) + "\n")
            stats[split] += 1
    return stats
