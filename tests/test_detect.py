from conftest import AI_PARA, HUMAN_PARA

from humanizer.detect import Detector
from humanizer.manuscript import build_manuscript
from humanizer.textproc import split_sentences


def _rules(text, section="introduction"):
    return {r.rule_id for r in Detector().sentence_reasons(text, section)}


def test_ai_paragraph_is_high_risk_and_human_paragraph_is_clean():
    det = Detector()
    ai = [det.cfg.risk(det.score(s.text, "introduction")) for s in split_sentences(AI_PARA)]
    human = [det.cfg.risk(det.score(s.text, "methods")) for s in split_sentences(HUMAN_PARA)]
    assert ai == ["high", "high", "high"]
    assert set(human) == {"none"}


def test_structural_rules():
    assert "STR_TRAILING_PARTICIPLE" in _rules("The EQE rose to 21%, underscoring the value of the new host.")
    assert "STR_TRANSITION_START" in _rules("Furthermore, the device was stable.")
    assert "STR_EM_DASH" in _rules("The host—a bipolar material—was used.")
    assert "STR_NOT_ONLY" in _rules("It not only improves efficiency but also extends lifetime.")
    assert "STR_HEDGE_STACK" in _rules("This could potentially reduce roll-off.")
    assert "STR_UNSUPPORTED_INTENSIFIER" in _rules("The device shows remarkable stability.")
    assert "STR_UNSUPPORTED_INTENSIFIER" not in _rules("The device shows remarkable stability of 1000 h.")


def test_allowlisted_engineering_words_are_not_flagged():
    assert _rules("A robust encapsulation enhanced the lifetime by 30% [4].", "methods") == set()


def test_paragraph_rules_and_overuse():
    uniform = " ".join(["Moreover, this pivotal film was annealed at a high temperature."] * 5)
    ms = build_manuscript("x", "text", [("Introduction", {}, True), (uniform, {}, False)])
    findings = Detector().analyze(ms)
    rules = {r.rule_id for f in findings for r in f.reasons}
    assert {"PAR_LOW_BURSTINESS", "PAR_TRANSITION_DENSITY", "LEX_OVERUSE"} <= rules


def test_methods_multiplier_lowers_lexical_weight():
    det = Detector()
    s = "We utilize a pivotal step."
    assert det.score(s, "methods") < det.score(s, "introduction")
