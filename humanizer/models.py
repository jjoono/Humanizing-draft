"""Shared data structures for manuscripts and analysis results."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

RISK_ORDER = {"none": 0, "low": 1, "medium": 2, "high": 3}


@dataclass
class Sentence:
    text: str
    start: int  # char offset within the paragraph text
    end: int


@dataclass
class Paragraph:
    index: int
    text: str
    section: str = "other"
    is_heading: bool = False
    sentences: list[Sentence] = field(default_factory=list)
    # Where the paragraph came from: docx paragraph index, or pdf page + bbox.
    source: dict[str, Any] = field(default_factory=dict)


@dataclass
class Manuscript:
    path: str
    kind: str  # "docx" | "pdf" | "text"
    paragraphs: list[Paragraph]
    references: list[str] = field(default_factory=list)

    def body(self) -> list[Paragraph]:
        return [p for p in self.paragraphs if not p.is_heading and p.section != "references"]


@dataclass
class Reason:
    rule_id: str
    category: str
    weight: float
    match: str
    message: str


@dataclass
class Suggestion:
    text: str
    note: str = ""
    source: str = "llm"  # "llm" | "dictionary"
    score: float | None = None  # detector score of the suggestion itself


@dataclass
class Finding:
    para_index: int
    sent_index: int
    section: str
    text: str
    start: int
    end: int
    score: float
    risk: str
    reasons: list[Reason] = field(default_factory=list)
    suggestions: list[Suggestion] = field(default_factory=list)


@dataclass
class ReferenceCheck:
    index: int
    text: str
    doi: str | None
    status: str  # "ok" | "doi_not_found" | "title_mismatch" | "no_match" | "unchecked" | "error"
    detail: str = ""


@dataclass
class AnalysisResult:
    manuscript: Manuscript
    findings: list[Finding]
    reference_checks: list[ReferenceCheck] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def by_risk(self, minimum: str = "low") -> list[Finding]:
        floor = RISK_ORDER[minimum]
        return [f for f in self.findings if RISK_ORDER[f.risk] >= floor]

    def summary(self) -> dict[str, Any]:
        sentences = sum(len(p.sentences) for p in self.manuscript.body())
        counts = {r: 0 for r in ("high", "medium", "low")}
        per_section: dict[str, dict[str, int]] = {}
        rule_hits: dict[str, int] = {}
        for f in self.findings:
            if f.risk in counts:
                counts[f.risk] += 1
                sec = per_section.setdefault(f.section, {"high": 0, "medium": 0, "low": 0})
                sec[f.risk] += 1
            for r in f.reasons:
                rule_hits[r.rule_id] = rule_hits.get(r.rule_id, 0) + 1
        weighted = 3 * counts["high"] + 2 * counts["medium"] + counts["low"]
        doc_score = round(100 * weighted / (3 * sentences), 1) if sentences else 0.0
        return {
            "sentences": sentences,
            "risk_counts": counts,
            "document_risk_score": doc_score,  # 0 (clean) .. 100 (every sentence high)
            "per_section": per_section,
            "top_rules": sorted(rule_hits.items(), key=lambda kv: -kv[1])[:10],
            "reference_issues": sum(1 for r in self.reference_checks if r.status not in ("ok", "unchecked")),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.manuscript.path,
            "summary": self.summary(),
            "findings": [asdict(f) for f in self.findings],
            "reference_checks": [asdict(r) for r in self.reference_checks],
            "notes": self.notes,
        }
