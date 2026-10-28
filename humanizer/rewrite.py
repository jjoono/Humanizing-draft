"""Correction suggestions (RULES.md section 4): Claude API with guards, plus a dictionary fallback."""
from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from importlib import resources
from pathlib import Path

import yaml

from .detect import Detector
from .models import RISK_ORDER, AnalysisResult, Finding, Suggestion
from .profile import StyleProfile
from .textproc import missing_protected

log = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-opus-5-5"

SYSTEM_PROMPT = """You are a copy editor for English research manuscripts in engineering: OLED, perovskite LED (PeLED), quantum-dot LED (QLED), optics and display technology.

Your reference style is peer-reviewed papers written before 2020 by research groups in the US and Europe: direct, specific and quantitative. Authors state results with numbers, use plain verbs (show, use, increase, reduce), keep one term per concept, mix short and long sentences, and rarely use em dashes, sentence-initial "Moreover/Furthermore/Notably", or closing clauses such as ", highlighting the importance of ...".

For each flagged sentence you receive, write 2 or 3 alternative versions that remove the listed problems while keeping the meaning exactly.

Hard rules:
1. Keep every number, unit, sign, percentage, citation marker (e.g. [12]), chemical formula, abbreviation (EQE, ITO, HTL, PEDOT:PSS) and figure/equation reference (Fig. 2a, Eq. (3)) character-for-character.
2. Do not add claims, data, hedges or citations that are not in the original. Do not drop technical content.
3. Keep tense and voice conventions of the section: Methods in past tense (passive voice is fine), Results in past tense, Discussion may hedge with "may" or "suggest".
4. Use the same technical terms as the surrounding paragraph.
5. Do not make the text casual and do not introduce errors to look human.
6. If a phrase adds nothing (e.g. "It is worth noting that"), deleting it is a valid fix.
7. Each `note` is one short sentence in Korean explaining what changed."""

SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "suggestions": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"text": {"type": "string"}, "note": {"type": "string"}},
                            "required": ["text", "note"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["id", "suggestions"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["items"],
    "additionalProperties": False,
}


def load_alternatives(path: str | Path | None = None) -> dict[str, list[str]]:
    p = Path(path) if path else Path(str(resources.files("humanizer") / "data" / "alternatives.yaml"))
    return {k.lower(): v for k, v in yaml.safe_load(p.read_text(encoding="utf-8")).items()}


def dictionary_suggestions(f: Finding, alternatives: dict[str, list[str]],
                           profile: StyleProfile | None = None) -> list[Suggestion]:
    """Rule R8: word-level replacements, ranked by how common they are in the human corpus."""
    out: list[Suggestion] = []
    seen: set[str] = set()
    for r in f.reasons:
        key = r.match.lower()
        if r.category != "lexical" or key in seen:
            continue
        seen.add(key)
        cands = alternatives.get(key) or alternatives.get(re.sub(r"(s|es|ed|ing)$", "", key)) or []
        if profile:
            cands = sorted(cands, key=lambda c: -(profile.rate(c) or 0.0))
        if cands:
            out.append(Suggestion(text=f"'{r.match}' → " + " / ".join(cands[:3]),
                                  note="사람 코퍼스 빈도순 대체어" if profile else "대체어 사전", source="dictionary"))
    return out


def _style_hints(profile: StyleProfile | None, section: str) -> str:
    if not profile or not (st := profile.section(section)):
        return ""
    return (f"Human reference corpus, {section} section: mean sentence length "
            f"{st.sent_len_mean:.0f} words (sd {st.sent_len_std:.0f}); "
            f"{100 * st.first_person_rate:.0f}% of sentences use 'we'; "
            f"{100 * st.passive_rate:.0f}% contain a passive construction.")


def _build_prompt(paragraph: str, section: str, items: list[tuple[int, Finding]], hints: str) -> str:
    flagged = "\n".join(
        f'<sentence id="{i}">{f.text}</sentence>\n<problems>' +
        "; ".join(f"{r.rule_id}: {r.match}" for r in f.reasons) + "</problems>"
        for i, f in items)
    return (f"<section>{section}</section>\n<paragraph>\n{paragraph}\n</paragraph>\n"
            + (f"<style_hints>{hints}</style_hints>\n" if hints else "")
            + f"<flagged>\n{flagged}\n</flagged>\n"
            "Return alternatives for every flagged sentence id.")


class ClaudeRewriter:
    def __init__(self, detector: Detector, profile: StyleProfile | None = None, model: str = DEFAULT_MODEL,
                 effort: str = "medium", max_suggestions: int = 3):
        import anthropic  # optional dependency: pip install "humanizer[llm]"

        self.anthropic = anthropic
        self.client = anthropic.Anthropic()
        self.detector = detector
        self.profile = profile
        self.model = model
        self.effort = effort
        self.max_suggestions = max_suggestions

    def _call(self, prompt: str) -> dict | None:
        a = self.anthropic
        try:
            resp = self.client.beta.messages.create(
                model=self.model,
                max_tokens=16000,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
                output_config={"effort": self.effort, "format": {"type": "json_schema", "schema": SCHEMA}},
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except a.RateLimitError as e:
            log.warning("rate limited, skipping paragraph: %s", e)
            return None
        except a.APIStatusError as e:
            log.warning("API error %s, skipping paragraph: %s", e.status_code, e.message)
            return None
        except a.APIConnectionError as e:
            log.warning("connection error, skipping paragraph: %s", e)
            return None
        if resp.stop_reason == "refusal":
            log.warning("request declined (%s)", getattr(resp.stop_details, "category", None))
            return None
        text = next((b.text for b in resp.content if b.type == "text"), "")
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            log.warning("unparseable response (stop_reason=%s)", resp.stop_reason)
            return None

    def suggest(self, result: AnalysisResult, min_risk: str = "medium") -> int:
        """Attach guarded suggestions to findings; returns the number of sentences that got any."""
        paras = {p.index: p for p in result.manuscript.paragraphs}
        groups: dict[int, list[Finding]] = defaultdict(list)
        for f in result.by_risk(min_risk):
            groups[f.para_index].append(f)
        done = 0
        for pidx, findings in groups.items():
            para = paras[pidx]
            items = list(enumerate(findings))
            data = self._call(_build_prompt(para.text, para.section, items, _style_hints(self.profile, para.section)))
            if not data:
                continue
            by_id = {it["id"]: it["suggestions"] for it in data.get("items", [])}
            for i, f in items:
                kept = []
                for s in by_id.get(i, []):
                    text = s["text"].strip()
                    lost = missing_protected(f.text, text)
                    if lost:  # rule R1
                        log.info("dropped suggestion that altered %s", lost)
                        continue
                    score = self.detector.score(text, f.section)
                    if RISK_ORDER[self.detector.cfg.risk(score)] >= RISK_ORDER[f.risk]:  # rule R7
                        continue
                    kept.append(Suggestion(text=text, note=s.get("note", ""), source="llm", score=score))
                f.suggestions = kept[: self.max_suggestions] + [s for s in f.suggestions if s.source != "llm"]
                done += bool(kept)
        return done
