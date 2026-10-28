"""End-to-end manuscript analysis."""
from __future__ import annotations

import logging
from pathlib import Path

from .detect import Detector, DetectorConfig
from .manuscript import load_manuscript
from .models import AnalysisResult
from .profile import StyleProfile
from .rewrite import ClaudeRewriter, dictionary_suggestions, load_alternatives

log = logging.getLogger(__name__)


def analyze_file(path: str | Path, *, profile_path: str | Path | None = None,
                 learned_path: str | Path | None = None, rules_path: str | Path | None = None,
                 allow: list[str] | None = None, suggest: bool = False, suggest_min_risk: str = "medium",
                 model: str | None = None, refcheck: bool = False, mailto: str | None = None) -> AnalysisResult:
    profile = StyleProfile.load(profile_path) if profile_path and Path(profile_path).exists() else None
    detector = Detector(DetectorConfig.load(rules_path, learned_path, allow), profile)
    manuscript = load_manuscript(path)
    result = AnalysisResult(manuscript, detector.analyze(manuscript))
    if profile is None:
        result.notes.append("스타일 프로파일 없이 시드 규칙만으로 분석했습니다 (build-profile 실행 후 정확도가 올라갑니다).")

    alternatives = load_alternatives()
    for f in result.findings:
        f.suggestions = dictionary_suggestions(f, alternatives, profile)

    if suggest:
        kwargs = {"model": model} if model else {}
        try:
            n = ClaudeRewriter(detector, profile, **kwargs).suggest(result, min_risk=suggest_min_risk)
            result.notes.append(f"Claude 교정안: {n}개 문장에 생성 (보호 토큰·재검사 통과분만 표시).")
        except ImportError:
            result.notes.append("anthropic 패키지가 없어 교정안 생성을 건너뛰었습니다: pip install 'humanizer[llm]'")

    if refcheck and manuscript.references:
        from .refcheck import check_references
        result.reference_checks = check_references(manuscript.references, mailto=mailto)
    return result


def write_outputs(result: AnalysisResult, out_dir: str | Path, *, min_risk: str = "medium",
                  formats: tuple[str, ...] = ("annotated", "docx", "pdf", "json")) -> list[Path]:
    from .report import write_docx_report, write_json, write_pdf_report

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stem = Path(result.manuscript.path).stem
    written: list[Path] = []
    if "annotated" in formats:
        kind = result.manuscript.kind
        if kind == "docx":
            from .io_docx import annotate_docx
            p = out / f"{stem}.annotated.docx"
            annotate_docx(result, p, min_risk=min_risk)
            written.append(p)
        elif kind == "pdf":
            from .io_pdf import annotate_pdf
            p = out / f"{stem}.annotated.pdf"
            annotate_pdf(result, p, min_risk=min_risk)
            written.append(p)
    if "json" in formats:
        p = out / f"{stem}.report.json"
        write_json(result, p)
        written.append(p)
    if "docx" in formats:
        p = out / f"{stem}.report.docx"
        write_docx_report(result, p, min_risk=min_risk)
        written.append(p)
    if "pdf" in formats:
        p = out / f"{stem}.report.pdf"
        write_pdf_report(result, p, min_risk=min_risk)
        written.append(p)
    return written
