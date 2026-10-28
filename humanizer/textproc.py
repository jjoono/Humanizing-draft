"""Text utilities: sentence splitting, tokenizing, section labels, protected tokens."""
from __future__ import annotations

import re
from collections import Counter

from .models import Sentence

# Tokens ending in "." that do not end a sentence in engineering prose.
ABBREVIATIONS = {
    "fig", "figs", "eq", "eqs", "ref", "refs", "no", "nos", "vol", "al", "i.e", "e.g",
    "etc", "vs", "ca", "approx", "cf", "resp", "ed", "eds", "sec", "secs", "tab",
    "dr", "prof", "mr", "ms", "st", "jpn", "appl", "phys", "lett", "chem", "mater",
    "adv", "opt", "nat", "sci", "rev", "inc", "ltd", "co", "corp", "max", "min",
}

_SENT_END = re.compile(r"[.!?](?:[\"')\]]+)?(?=\s+)")
_WORD = re.compile(r"[A-Za-z][A-Za-z'\-]*[A-Za-z]|[A-Za-z]")

SECTION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("abstract", re.compile(r"^(abstract|summary)$")),
    ("introduction", re.compile(r"^(introduction|background|motivation)$")),
    ("methods", re.compile(
        r"^(methods?|materials and methods|experimental( section| details| methods| procedures?)?|"
        r"device fabrication.*|fabrication.*|sample preparation.*|characteri[sz]ation.*|"
        r"simulation( methods?| details)?|theory|theoretical (model|background)|model)$")),
    ("results", re.compile(r"^(results( and discussion)?|results & discussion)$")),
    ("discussion", re.compile(r"^(discussion|analysis)$")),
    ("conclusion", re.compile(r"^(conclusions?|concluding remarks|summary and (conclusions?|outlook)|outlook)$")),
    ("references", re.compile(r"^(references?|bibliography|literature cited|notes and references)$")),
    ("backmatter", re.compile(
        r"^(acknowledge?ments?|funding|author contributions?|competing interests?|"
        r"conflicts? of interest|data availability|supporting information|supplementary (information|material))$")),
]

_HEADING_NUMBER = re.compile(r"^\s*(?:\d+(?:\.\d+)*\.?|[IVX]+\.|[A-H]\.)\s*")
CAPTION_RE = re.compile(r"^(fig(?:ure)?\.?|table|scheme)\s*s?\d+[a-z]?[.:|]", re.I)


def classify_heading(text: str) -> str | None:
    """Return a normalized section label if `text` looks like a section heading."""
    t = _HEADING_NUMBER.sub("", text.strip()).strip(" .:").lower()
    if not t or len(t) > 80:
        return None
    for label, pat in SECTION_PATTERNS:
        if pat.match(t):
            return label
    return None


def split_sentences(text: str) -> list[Sentence]:
    """Split a paragraph into sentences, keeping char offsets.

    Rule-based on purpose: it must not split on "Fig. 2", "et al.", "Eq. (3)",
    "ca. 5 nm" or author initials, which are everywhere in engineering papers.
    """
    sentences: list[Sentence] = []
    start = 0
    n = len(text)
    for m in _SENT_END.finditer(text):
        end = m.end()
        if text[m.start()] == ".":
            before = text[start:m.start()]
            last = re.search(r"([A-Za-z.]+)$", before)
            token = last.group(1).lower().rstrip(".") if last else ""
            if token in ABBREVIATIONS or token.split(".")[-1] in ABBREVIATIONS:
                continue
            if (last and len(last.group(1)) == 1 and last.group(1).isupper()
                    and not re.search(r"\d\s*[A-Z]$", before)):
                continue  # initial "C. W. Tang", but not a unit as in "at 300 K."
            if re.search(r"\d$", before) and re.match(r"\s+\d", text[end:]):
                continue
        nxt = re.match(r"\s+(\S)", text[end:])
        if not nxt or not (nxt.group(1).isupper() or nxt.group(1) in "([\"'" or nxt.group(1).isdigit()):
            continue
        seg = text[start:end].strip()
        if seg:
            s = start + (len(text[start:end]) - len(text[start:end].lstrip()))
            sentences.append(Sentence(seg, s, s + len(seg)))
        start = end
    tail = text[start:n].strip()
    if tail:
        s = start + (len(text[start:n]) - len(text[start:n].lstrip()))
        sentences.append(Sentence(tail, s, s + len(tail)))
    return sentences


def words(text: str) -> list[str]:
    return [w.lower() for w in _WORD.findall(text)]


def ngrams(tokens: list[str], n: int) -> list[str]:
    return [" ".join(tokens[i:i + n]) for i in range(len(tokens) - n + 1)]


def count_ngrams(texts, max_n: int = 3) -> Counter:
    c: Counter = Counter()
    for t in texts:
        toks = words(t)
        for n in range(1, max_n + 1):
            c.update(ngrams(toks, n))
    return c


# --- citation normalization -------------------------------------------------

_CIT_PATTERNS = [
    re.compile(r"\[\s*\d+(?:\s*[,–—\-]\s*\d+)*\s*\]"),  # [12], [3-5], [1, 4]
    re.compile(r"\((?:[A-Z][A-Za-z\-]+(?: et al\.)?(?:,? (?:and|&) [A-Z][A-Za-z\-]+)?,? \d{4}[a-z]?;?\s*)+\)"),
]


def normalize_citations(text: str) -> str:
    for pat in _CIT_PATTERNS:
        text = pat.sub("<CIT>", text)
    return text


def dehyphenate(text: str) -> str:
    text = re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", text)
    return re.sub(r"\s*\n\s*", " ", text).strip()


# --- protected tokens (rule R1) --------------------------------------------

_PROTECTED = [
    re.compile(r"\[\s*\d+(?:\s*[,–—\-]\s*\d+)*\s*\]"),               # numeric citations
    re.compile(r"\b(?:Figs?|Eqs?|Tables?|Refs?)\.?\s*\(?S?\d+[a-z]?\)?(?:[–\-,]\s*\d*[a-z]?)*", re.I),
    re.compile(r"[±~<>≤≥]?\s*-?\d+(?:[.,]\d+)?(?:\s*[×x]\s*10\^?[−\-]?\d+)?\s*%?"),  # numbers
    re.compile(r"\b(?=[A-Za-z0-9():]*\d)(?=[A-Za-z0-9():]*[A-Z])[A-Za-z][A-Za-z0-9():]{1,}\b"),  # CsPbBr3, Ir(ppy)3
    re.compile(r"\b[A-Z][A-Z0-9]{1,}(?::[A-Z0-9]+)?s?\b"),                     # EQE, ITO, PEDOT:PSS, OLEDs
]


def protected_tokens(text: str) -> Counter:
    found: Counter = Counter()
    for pat in _PROTECTED:
        for m in pat.finditer(text):
            tok = re.sub(r"\s+", "", m.group(0))
            if tok and any(ch.isalnum() for ch in tok):
                found[tok] += 1
    return found


def missing_protected(original: str, rewritten: str) -> list[str]:
    """Protected tokens present in `original` but dropped or altered in `rewritten`."""
    before, after = protected_tokens(original), protected_tokens(rewritten)
    return sorted(tok for tok, n in before.items() if after.get(tok, 0) < n)
