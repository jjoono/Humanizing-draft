"""False-positive / recall measurement on held-out corpora (RULES.md E1-E5)."""
from __future__ import annotations

from collections import Counter

from .detect import Detector
from .models import Paragraph
from .profile import iter_corpus
from .textproc import split_sentences

RELEASE_GATE = {"high": 0.02, "medium_or_higher": 0.10}  # rule E2, on human text


def _rates(detector: Detector, path: str) -> dict:
    risks: Counter = Counter()
    scores: list[float] = []
    for doc in iter_corpus(path):
        for sec in doc.get("sections", []):
            for text in sec.get("paragraphs", []):
                para = Paragraph(0, text, sec["section"], sentences=split_sentences(text))
                extra = detector.paragraph_reasons(para)
                for i, s in enumerate(para.sentences):
                    score = sum(r.weight for r in detector.sentence_reasons(s.text, para.section) + extra.get(i, []))
                    scores.append(score)
                    risks[detector.cfg.risk(score)] += 1
    n = sum(risks.values()) or 1
    return {
        "sentences": sum(risks.values()),
        "high": risks["high"] / n,
        "medium_or_higher": (risks["high"] + risks["medium"]) / n,
        "any_flag": (n - risks["none"]) / n,
        "scores": scores,
    }


def _auc(pos: list[float], neg: list[float]) -> float | None:
    """Probability that a random AI sentence scores above a random human one (ties count half)."""
    if not pos or not neg:
        return None
    ranked = sorted([(s, 1) for s in pos] + [(s, 0) for s in neg])
    rank_sum, i = 0.0, 0
    while i < len(ranked):
        j = i
        while j < len(ranked) and ranked[j][0] == ranked[i][0]:
            j += 1
        avg = (i + j + 1) / 2  # 1-based average rank of the tie group
        rank_sum += avg * sum(lbl for _, lbl in ranked[i:j])
        i = j
    return (rank_sum - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg))


def evaluate(detector: Detector, human_path: str, ai_path: str | None = None) -> dict:
    human = _rates(detector, human_path)
    report = {"human": {k: v for k, v in human.items() if k != "scores"}}
    report["release_gate_passed"] = (human["high"] <= RELEASE_GATE["high"]
                                     and human["medium_or_higher"] <= RELEASE_GATE["medium_or_higher"])
    if ai_path:
        ai = _rates(detector, ai_path)
        report["ai"] = {k: v for k, v in ai.items() if k != "scores"}
        report["auc"] = _auc(ai["scores"], human["scores"])
    return report
