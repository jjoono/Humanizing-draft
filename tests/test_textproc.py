from humanizer.textproc import classify_heading, missing_protected, normalize_citations, split_sentences


def test_split_keeps_engineering_abbreviations_together():
    text = ("As shown in Fig. 2a, the EQE was 20.3% (ca. 5 nm shift). Tang et al. reported this [1]. "
            "C. W. Tang used Eq. (3) here. The film was annealed at 300 K. The decay was fast.")
    got = [s.text for s in split_sentences(text)]
    assert got == [
        "As shown in Fig. 2a, the EQE was 20.3% (ca. 5 nm shift).",
        "Tang et al. reported this [1].",
        "C. W. Tang used Eq. (3) here.",
        "The film was annealed at 300 K.",
        "The decay was fast.",
    ]


def test_offsets_point_into_paragraph():
    text = "First sentence here.  Second one follows."
    for s in split_sentences(text):
        assert text[s.start:s.end] == s.text


def test_classify_heading():
    assert classify_heading("2. Experimental Section") == "methods"
    assert classify_heading("Results and Discussion") == "results"
    assert classify_heading("III. CONCLUSIONS") == "conclusion"
    assert classify_heading("References") == "references"
    assert classify_heading("Optical simulation of the stack") is None


def test_normalize_citations():
    assert normalize_citations("as reported [3-5] and (Kim et al., 2018).") == "as reported <CIT> and <CIT>."


def test_missing_protected_detects_changed_numbers_and_citations():
    orig = "The EQE of 20.3% at 5 V for CsPbBr3 in Fig. 2a [12] exceeds that of ITO devices."
    assert missing_protected(orig, "CsPbBr3 devices in Fig. 2a [12] reach an EQE of 20.3% at 5 V, above ITO devices.") == []
    lost = missing_protected(orig, "The EQE of 20% at 5 V for CsPbBr3 in Fig. 2a exceeds that of ITO devices.")
    assert "20.3%" in lost and "[12]" in lost
