"""Sentence-level AI-style risk detector (RULES.md section 3)."""
from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from statistics import mean, pstdev

import yaml

from .models import Finding, Manuscript, Paragraph, Reason
from .profile import StyleProfile
from .textproc import normalize_citations, words

_NUMBER_OR_CIT = re.compile(r"\d|<CIT>|\[\d")
_TRIAD = re.compile(r"\b([a-z]+), ([a-z]+),? and ([a-z]+)\b", re.I)
_ADJ_SUFFIX = re.compile(r"(ive|al|able|ible|ient|ent|ous|ful|less|ic|ary|ized|ised|ing)$")
_THIS_SUMMARY = re.compile(
    r"^(this|these|such|our) (\w+ ){0,3}(highlights?|underscores?|showcases?|emphasizes?|paves?|"
    r"represents? a (significant|major|key|crucial)|marks? a|opens?)\b", re.I)
_SUMMARY_END = re.compile(
    r"^(overall|in summary|in essence|collectively|ultimately|taken together|"
    r"(these|our|the) (results|findings|observations) (collectively )?(highlight|underscore|demonstrate|emphasize|showcase))\b", re.I)
_HEDGE_STACK = re.compile(r"\b(could|may|might|can) (potentially|possibly|perhaps)\b", re.I)
_NOT_ONLY = re.compile(r"\bnot only\b.{1,120}?\bbut (also)?\b", re.I)


def _default_rules_path() -> Path:
    return Path(str(resources.files("humanizer") / "data" / "detector.yaml"))


@dataclass
class DetectorConfig:
    thresholds: dict[str, float]
    section_multipliers: dict[str, float]
    allowlist: set[str]
    words: dict[str, float]
    phrases: list[tuple[re.Pattern[str], float, str]]
    transition_starters: dict[str, float]
    strong_participles: set[str]
    weak_participles: set[str]
    intensifiers: set[str]
    learned: dict[str, float] = field(default_factory=dict)

    @classmethod
    def load(cls, rules_path: str | Path | None = None, learned_path: str | Path | None = None,
             extra_allow: list[str] | None = None) -> "DetectorConfig":
        raw = yaml.safe_load(Path(rules_path or _default_rules_path()).read_text(encoding="utf-8"))
        allow = {w.lower() for w in raw.get("allowlist", [])} | {w.lower() for w in (extra_allow or [])}
        learned: dict[str, float] = {}
        if learned_path and Path(learned_path).exists():
            for item in json.loads(Path(learned_path).read_text(encoding="utf-8")):
                if item["term"] not in allow:
                    learned[item["term"]] = float(item["weight"])
        tp = raw.get("trailing_participles", {})
        return cls(
            thresholds=raw["thresholds"],
            section_multipliers=raw.get("section_multipliers", {"default": 1.0}),
            allowlist=allow,
            words={k.lower(): float(v) for k, v in raw.get("words", {}).items() if k.lower() not in allow},
            phrases=[(re.compile(p["pattern"], re.I), float(p["weight"]), p["pattern"]) for p in raw.get("phrases", [])],
            transition_starters={k.lower(): float(v) for k, v in raw.get("transition_starters", {}).items()},
            strong_participles=set(tp.get("strong", [])),
            weak_participles=set(tp.get("weak", [])),
            intensifiers={w.lower() for w in raw.get("intensifiers", [])},
            learned=learned,
        )

    def risk(self, score: float) -> str:
        t = self.thresholds
        if score >= t["high"]:
            return "high"
        if score >= t["medium"]:
            return "medium"
        if score >= t["low"]:
            return "low"
        return "none"


class Detector:
    def __init__(self, config: DetectorConfig | None = None, profile: StyleProfile | None = None):
        self.cfg = config or DetectorConfig.load()
        self.profile = profile

    # ---- sentence level ---------------------------------------------------

    def sentence_reasons(self, text: str, section: str = "other") -> list[Reason]:
        cfg = self.cfg
        mult = cfg.section_multipliers.get(section, cfg.section_multipliers.get("default", 1.0))
        reasons: list[Reason] = []
        norm = normalize_citations(text)
        toks = words(norm)
        lower = norm.lower()
        phrase_spans: list[tuple[int, int]] = []

        for pat, w, src in cfg.phrases:
            for m in pat.finditer(norm):
                phrase_spans.append(m.span())
                reasons.append(Reason("LEX_PHRASE", "lexical", round(w * mult, 2), m.group(0),
                                      f"AI 상투 구문 '{m.group(0)}'" + self._rate_note(m.group(0))))

        for m in re.finditer(r"[A-Za-z][A-Za-z\-]*", norm):
            tok = m.group(0).lower()
            w = cfg.words.get(tok)
            if w is None or any(s <= m.start() < e for s, e in phrase_spans):
                continue
            reasons.append(Reason("LEX_WORD", "lexical", round(w * mult, 2), m.group(0),
                                  f"AI 과다 사용 단어 '{m.group(0)}'" + self._rate_note(tok)))

        if cfg.learned:
            seen = {r.match.lower() for r in reasons}
            for n in (3, 2, 1):
                for i in range(len(toks) - n + 1):
                    term = " ".join(toks[i:i + n])
                    w = cfg.learned.get(term)
                    if w and term not in seen and not any(term in s for s in seen):
                        seen.add(term)
                        reasons.append(Reason("LEX_LEARNED", "lexical", round(w * mult, 2), term,
                                              f"대조 코퍼스에서 AI 쪽으로 치우친 표현 '{term}'" + self._rate_note(term)))

        # Structure
        first = re.match(r"\s*([A-Za-z]+(?: [a-z]+)?)\s*,", norm)
        if first:
            key = first.group(1).lower()
            w = cfg.transition_starters.get(key) or cfg.transition_starters.get(key.split()[0])
            if w:
                reasons.append(Reason("STR_TRANSITION_START", "structure", w, first.group(1),
                                      f"접속부사 '{first.group(1)},'로 문장 시작" + self._starter_note(key.split()[0], section)))

        tail = re.search(r",\s+(thereby\s+|thus\s+)?([a-z]+ing)\b[^,;]*[.!?]?$", norm)
        if tail:
            verb = tail.group(2).lower()
            if verb in cfg.strong_participles:
                reasons.append(Reason("STR_TRAILING_PARTICIPLE", "structure", 1.2, tail.group(0).strip(),
                                      f"문장 끝 분사구 ', {verb} …' (AI가 결과의 의미를 덧붙이는 전형적 패턴)"))
            elif verb in cfg.weak_participles:
                reasons.append(Reason("STR_TRAILING_PARTICIPLE", "structure", 0.4, tail.group(0).strip(),
                                      f"문장 끝 분사구 ', {verb} …'"))

        if "—" in norm or " -- " in norm:
            reasons.append(Reason("STR_EM_DASH", "structure", 1.0, "—",
                                  "em dash(—) 사용: 2020년 이전 공학 논문에서는 드묾" + self._dash_note(section)))
        m = _NOT_ONLY.search(norm)
        if m:
            reasons.append(Reason("STR_NOT_ONLY", "structure", 1.0, m.group(0)[:60], "'not only … but also' 구문"))
        for m in _TRIAD.finditer(norm):
            items = [g.lower() for g in m.groups()]
            if sum(bool(_ADJ_SUFFIX.search(x)) for x in items) >= 2 and not any(x in ("and", "or") for x in items):
                reasons.append(Reason("STR_TRIAD", "structure", 0.6, m.group(0),
                                      "형용사/추상명사 3개 나열 (AI의 'X, Y, and Z' 리듬)"))
                break
        m = _THIS_SUMMARY.match(norm.strip())
        if m:
            reasons.append(Reason("STR_THIS_SUMMARY", "structure", 1.0, m.group(0), "'This/These … highlights/underscores …' 식 자기 요약"))
        if norm.strip().endswith("?"):
            reasons.append(Reason("STR_RHETORICAL_Q", "structure", 0.8, "?", "수사 의문문"))
        m = _HEDGE_STACK.search(norm)
        if m:
            reasons.append(Reason("STR_HEDGE_STACK", "structure", 1.0, m.group(0), f"중복 hedging '{m.group(0)}'"))
        intens = [t for t in toks if t in cfg.intensifiers]
        if intens and not _NUMBER_OR_CIT.search(norm):
            reasons.append(Reason("STR_UNSUPPORTED_INTENSIFIER", "structure", 0.6, intens[0],
                                  f"수치·인용 없이 강조어 '{intens[0]}' 사용"))
        if self.profile:
            st = self.profile.section(section)
            if st and st.sent_len_std > 0 and len(toks) > st.sent_len_mean + 2.5 * st.sent_len_std:
                reasons.append(Reason("STR_LONG_SENTENCE", "structure", 0.4, f"{len(toks)} words",
                                      f"문장 길이 {len(toks)}어절 (사람 기준 평균 {st.sent_len_mean:.0f}±{st.sent_len_std:.0f})"))
        return reasons

    def score(self, text: str, section: str = "other") -> float:
        return round(sum(r.weight for r in self.sentence_reasons(text, section)), 2)

    # ---- paragraph / document level --------------------------------------

    def paragraph_reasons(self, para: Paragraph) -> dict[int, list[Reason]]:
        extra: dict[int, list[Reason]] = {}
        sents = para.sentences
        if len(sents) >= 4:
            lens = [len(words(s.text)) for s in sents]
            m = mean(lens)
            cv = pstdev(lens) / m if m else 0.0
            ref = 0.25
            if self.profile and (st := self.profile.section(para.section)) and st.para_cv_median:
                ref = min(0.25, 0.6 * st.para_cv_median)
            if cv < ref:
                for i in range(len(sents)):
                    extra.setdefault(i, []).append(Reason(
                        "PAR_LOW_BURSTINESS", "paragraph", 0.6, f"CV={cv:.2f}",
                        f"문단 내 문장 길이가 지나치게 균일함 (CV {cv:.2f} < 기준 {ref:.2f})"))
        if len(sents) >= 3:
            starts = [i for i, s in enumerate(sents)
                      if (mm := re.match(r"\s*([A-Za-z]+)\s*,", s.text))
                      and mm.group(1).lower() in self.cfg.transition_starters]
            if len(starts) / len(sents) >= 0.4:
                for i in starts:
                    extra.setdefault(i, []).append(Reason(
                        "PAR_TRANSITION_DENSITY", "paragraph", 0.6, f"{len(starts)}/{len(sents)}",
                        f"문단 문장 {len(starts)}/{len(sents)}개가 접속부사로 시작"))
        if len(sents) >= 2 and para.section not in ("conclusion", "abstract"):
            last = sents[-1].text.strip()
            m = _SUMMARY_END.match(last)
            if m:
                extra.setdefault(len(sents) - 1, []).append(Reason(
                    "PAR_SUMMARY_END", "paragraph", 0.8, m.group(0), "결론부가 아닌 문단을 요약 문장으로 마무리"))
        return extra

    def analyze(self, manuscript: Manuscript, min_risk: str = "low") -> list[Finding]:
        findings: list[Finding] = []
        usage: Counter = Counter()
        for para in manuscript.body():
            extra = self.paragraph_reasons(para)
            for si, sent in enumerate(para.sentences):
                reasons = self.sentence_reasons(sent.text, para.section) + extra.get(si, [])
                for r in reasons:
                    if r.category == "lexical":
                        usage[r.match.lower()] += 1
                findings.append(self._finding(para, si, reasons))
        # LEX_OVERUSE: the same marker used 3+ times in one document.
        overused = {term for term, n in usage.items() if n >= 3}
        if overused:
            for f in findings:
                hits = {r.match.lower() for r in f.reasons if r.category == "lexical"} & overused
                for term in sorted(hits):
                    f.reasons.append(Reason("LEX_OVERUSE", "lexical", 0.5, term,
                                            f"'{term}'이(가) 문서에서 {usage[term]}회 반복됨"))
                f.score = round(sum(r.weight for r in f.reasons), 2)
                f.risk = self.cfg.risk(f.score)
        floor = {"low": 1, "medium": 2, "high": 3}[min_risk]
        rank = {"none": 0, "low": 1, "medium": 2, "high": 3}
        return [f for f in findings if rank[f.risk] >= floor]

    def _finding(self, para: Paragraph, si: int, reasons: list[Reason]) -> Finding:
        sent = para.sentences[si]
        score = round(sum(r.weight for r in reasons), 2)
        return Finding(para.index, si, para.section, sent.text, sent.start, sent.end, score,
                       self.cfg.risk(score), reasons)

    # ---- evidence notes ---------------------------------------------------

    def _rate_note(self, term: str) -> str:
        if not self.profile:
            return ""
        rate = self.profile.rate(term.lower())
        return f" (사람 코퍼스 {rate:.1f}회/백만 단어)" if rate else " (사람 코퍼스에서 거의 쓰이지 않음)"

    def _starter_note(self, word: str, section: str) -> str:
        if not self.profile or not (st := self.profile.section(section)):
            return ""
        share = st.starters.get(word, 0.0)
        return f" (사람 코퍼스 {section} 문장의 {100 * share:.2f}%)"

    def _dash_note(self, section: str) -> str:
        if not self.profile or not (st := self.profile.section(section)):
            return ""
        return f" (사람 코퍼스 {st.em_dash_per_1k_sent:.1f}회/1천 문장)"

