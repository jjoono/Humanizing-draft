from conftest import AI_PARA

from humanizer.detect import Detector, DetectorConfig
from humanizer.evaluate import evaluate
from humanizer.models import AnalysisResult
from humanizer.pipeline import analyze_file
from humanizer.profile import StyleProfile, build_profile, iter_corpus, learn_markers
from humanizer.rewrite import ClaudeRewriter


def test_profile_roundtrip(corpora, tmp_path):
    human, _ = corpora
    prof = build_profile(iter_corpus(human), min_count=1)
    assert prof.documents == 5 and "methods" in prof.sections
    assert prof.sections["methods"].passive_rate > 0
    prof.save(tmp_path / "p.json")
    again = StyleProfile.load(tmp_path / "p.json")
    assert again.sections["methods"].sent_len_mean == prof.sections["methods"].sent_len_mean
    assert again.rate("devices") > 0


def test_learn_markers_finds_ai_terms(corpora, tmp_path):
    human, ai = corpora
    markers = learn_markers(iter_corpus(human), iter_corpus(ai), z_min=1.0)
    terms = {m["term"] for m in markers}
    assert "garnered" in terms or "interplay" in terms
    assert "devices" not in terms


def test_evaluate_reports_gate(corpora):
    human, ai = corpora
    rep = evaluate(Detector(), str(human), str(ai))
    assert rep["human"]["high"] == 0.0 and rep["release_gate_passed"]
    assert rep["ai"]["high"] > 0.5 and rep["auc"] > 0.9


def test_learned_markers_are_used(tmp_path):
    p = tmp_path / "learned.json"
    p.write_text('[{"term": "toward commercialization", "weight": 1.5, "z": 9}]')
    det = Detector(DetectorConfig.load(learned_path=p))
    assert "LEX_LEARNED" in {r.rule_id for r in det.sentence_reasons("This is a step toward commercialization.")}


class _FakeRewriter(ClaudeRewriter):
    """Skips the API client; returns canned model output."""

    def __init__(self, detector, canned):
        self.detector, self.profile, self.max_suggestions, self.canned = detector, None, 3, canned

    def _call(self, prompt):
        return self.canned


def test_rewrite_guards_drop_bad_suggestions(sample_docx):
    result: AnalysisResult = analyze_file(sample_docx)
    target = next(f for f in result.findings if f.text.startswith("This work underscores"))
    para_findings = [f for f in result.by_risk("medium") if f.para_index == target.para_index]
    idx = para_findings.index(target)
    canned = {"items": [{"id": idx, "suggestions": [
        {"text": "Interface engineering is therefore important for commercialization.", "note": "ok"},
        {"text": "This work underscores the pivotal importance of interfaces.", "note": "still AI"},
    ]}]}
    _FakeRewriter(Detector(), canned).suggest(result)
    llm = [s for s in target.suggestions if s.source == "llm"]
    assert [s.text for s in llm] == ["Interface engineering is therefore important for commercialization."]


def test_rewrite_guard_protects_numbers(sample_docx):
    result = analyze_file(sample_docx)
    f = result.by_risk("medium")[0]
    f.text = "Moreover, the EQE reached 20.3% [5], highlighting the value of the host."
    canned = {"items": [{"id": 0, "suggestions": [
        {"text": "The EQE reached 20%.", "note": "dropped data"},
        {"text": "The EQE reached 20.3% [5] with this host.", "note": "ok"},
    ]}]}
    result.findings = [f]
    _FakeRewriter(Detector(), canned).suggest(result)
    assert [s.text for s in f.suggestions if s.source == "llm"] == ["The EQE reached 20.3% [5] with this host."]
    assert AI_PARA  # fixture text is importable for ad-hoc debugging
