"""Human style profile (RULES.md section 2) and contrastive marker learning (LEX_LEARNED)."""
from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean, pstdev
from typing import Iterable, Iterator

from .textproc import count_ngrams, normalize_citations, split_sentences, words

PROFILE_SECTIONS = ("abstract", "introduction", "methods", "results", "discussion", "conclusion", "caption")
_PASSIVE = re.compile(r"\b(is|are|was|were|be|been|being)\s+(\w+ly\s+)?\w+(ed|en)\b", re.I)
_FIRST_PERSON = re.compile(r"\b(we|our|us)\b", re.I)


def iter_corpus(path: str | Path) -> Iterator[dict]:
    """Yield docs from a JSONL corpus: {"id", "meta", "sections": [{"section", "paragraphs"}]}."""
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield json.loads(line)


def iter_paragraphs(docs: Iterable[dict]) -> Iterator[tuple[str, str]]:
    for doc in docs:
        for sec in doc.get("sections", []):
            for para in sec.get("paragraphs", []):
                yield sec.get("section", "other"), para


@dataclass
class SectionStats:
    sentences: int = 0
    words: int = 0
    sent_len_mean: float = 0.0
    sent_len_std: float = 0.0
    para_cv_median: float = 0.0  # median per-paragraph coefficient of variation of sentence length
    para_len_mean: float = 0.0   # sentences per paragraph
    starters: dict[str, float] = field(default_factory=dict)  # first word -> share of sentences
    first_person_rate: float = 0.0
    passive_rate: float = 0.0
    em_dash_per_1k_sent: float = 0.0
    semicolon_per_1k_sent: float = 0.0


@dataclass
class StyleProfile:
    total_words: int
    per_million: dict[str, float]  # n-gram -> occurrences per million words (all sections)
    sections: dict[str, SectionStats]
    documents: int = 0

    def rate(self, term: str) -> float | None:
        return self.per_million.get(term.lower()) if self.per_million else None

    def section(self, name: str) -> SectionStats | None:
        return self.sections.get(name) or self.sections.get("all")

    def save(self, path: str | Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        data = {
            "documents": self.documents,
            "total_words": self.total_words,
            "per_million": self.per_million,
            "sections": {k: vars(v) for k, v in self.sections.items()},
        }
        Path(path).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "StyleProfile":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(
            total_words=data["total_words"],
            per_million=data["per_million"],
            sections={k: SectionStats(**v) for k, v in data["sections"].items()},
            documents=data.get("documents", 0),
        )


def build_profile(docs: Iterable[dict], min_count: int = 3, max_n: int = 3) -> StyleProfile:
    """Aggregate n-gram rates and per-section sentence statistics from a human corpus.

    Only counts and short n-grams are stored, never sentences (rule C6).
    """
    docs = list(docs)
    grams: Counter = Counter()
    total_words = 0
    acc: dict[str, dict] = defaultdict(lambda: {
        "lens": [], "cvs": [], "para_lens": [], "starters": Counter(),
        "fp": 0, "passive": 0, "dash": 0, "semi": 0,
    })
    for section, para in iter_paragraphs(docs):
        para = normalize_citations(para)
        sents = split_sentences(para)
        lens = [len(words(s.text)) for s in sents]
        toks = words(para)
        total_words += len(toks)
        grams.update(count_ngrams([para], max_n=max_n))
        for key in (section, "all"):
            a = acc[key]
            a["lens"].extend(lens)
            a["para_lens"].append(len(sents))
            if len(lens) >= 4 and mean(lens) > 0:
                a["cvs"].append(pstdev(lens) / mean(lens))
            for s in sents:
                w = words(s.text)
                if w:
                    a["starters"][w[0]] += 1
                a["fp"] += bool(_FIRST_PERSON.search(s.text))
                a["passive"] += bool(_PASSIVE.search(s.text))
                a["dash"] += s.text.count("—")
                a["semi"] += s.text.count(";")

    sections: dict[str, SectionStats] = {}
    for key, a in acc.items():
        n = len(a["lens"])
        if not n:
            continue
        cvs = sorted(a["cvs"])
        sections[key] = SectionStats(
            sentences=n,
            words=sum(a["lens"]),
            sent_len_mean=round(mean(a["lens"]), 2),
            sent_len_std=round(pstdev(a["lens"]), 2),
            para_cv_median=round(cvs[len(cvs) // 2], 3) if cvs else 0.0,
            para_len_mean=round(mean(a["para_lens"]), 2),
            starters={w: round(c / n, 4) for w, c in a["starters"].most_common(60)},
            first_person_rate=round(a["fp"] / n, 4),
            passive_rate=round(a["passive"] / n, 4),
            em_dash_per_1k_sent=round(1000 * a["dash"] / n, 2),
            semicolon_per_1k_sent=round(1000 * a["semi"] / n, 2),
        )
    scale = 1e6 / max(total_words, 1)
    per_million = {g: round(c * scale, 3) for g, c in grams.items() if c >= min_count}
    return StyleProfile(total_words=total_words, per_million=per_million, sections=sections, documents=len(docs))


# --- contrastive marker learning --------------------------------------------

STOPWORDS = set("""
a an the of to in on at by for from with and or but as is are was were be been being this that these those it its
we our us they their which who whom whose than then there here into onto over under between among also not no can could
may might will would should shall do does did has have had such so very more most less least other each both all any
""".split())


def learn_markers(human_docs: Iterable[dict], ai_docs: Iterable[dict], *, prior_scale: float = 500.0,
                  min_ai_count: int = 5, z_min: float = 3.0, top_k: int = 300) -> list[dict]:
    """Log-odds ratio with an informative Dirichlet prior (Monroe, Colaresi & Quinn 2008).

    Returns n-grams over-represented in the AI corpus relative to the human corpus.
    With paired data (AI rewrites of the same paragraphs) topic words cancel out and
    what remains is mostly style.
    """
    h = count_ngrams((p for _, p in iter_paragraphs(human_docs)), max_n=3)
    a = count_ngrams((p for _, p in iter_paragraphs(ai_docs)), max_n=3)
    n_h, n_a = sum(h.values()), sum(a.values())
    total = n_h + n_a
    out = []
    for term in set(a) | set(h):
        ya, yh = a.get(term, 0), h.get(term, 0)
        if ya < min_ai_count:
            continue
        toks = term.split()
        if all(t in STOPWORDS for t in toks) or any(ch.isdigit() for ch in term) or len(term) < 4:
            continue
        alpha = prior_scale * (ya + yh) / total
        if alpha <= 0:
            continue
        a0 = prior_scale
        la = math.log((ya + alpha) / (n_a + a0 - ya - alpha))
        lh = math.log((yh + alpha) / (n_h + a0 - yh - alpha))
        z = (la - lh) / math.sqrt(1.0 / (ya + alpha) + 1.0 / (yh + alpha))
        if z >= z_min:
            out.append({
                "term": term,
                "z": round(z, 2),
                "ai_count": ya,
                "human_count": yh,
                "weight": round(min(2.0, 0.4 + z / 6.0), 2),
            })
    out.sort(key=lambda d: -d["z"])
    return out[:top_k]
