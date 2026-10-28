from humanizer.config import PRIORITY_WEIGHTS
from humanizer.corpus.extract import is_holdout, parse_jats
from humanizer.corpus.openalex import _abstract, is_review, on_topic, priority

LONG = "In all devices the emission layer was deposited by thermal evaporation under high vacuum and its thickness was varied"

JATS = f"""<article><front><article-meta><abstract><p>{LONG} from 10 to 40 nm in this study.</p></abstract>
</article-meta></front><body>
<sec><title>1. Introduction</title><p>{LONG} as reported earlier<xref ref-type="bibr" rid="b1">1</xref>.</p></sec>
<sec sec-type="methods"><title>Experimental</title>
  <sec><title>Device fabrication</title><p>{LONG}<disp-formula>E = mc^2</disp-formula> before encapsulation.</p></sec>
</sec>
<sec><title>Acknowledgements</title><p>{LONG} thanks to the funding agency for support here.</p></sec>
</body></article>""".encode()


def test_parse_jats_sections_and_citations():
    secs = {s["section"]: s["paragraphs"] for s in parse_jats(JATS)}
    assert set(secs) == {"abstract", "introduction", "methods"}
    assert "<CIT>" in secs["introduction"][0]
    assert "mc^2" not in secs["methods"][0] and "before encapsulation" in secs["methods"][0]


def test_priority_prefers_old_cited_us_eu_papers():
    base = {"cited_by_count": 50, "year": 2018, "author_countries": [["CN"], ["CN"]], "venue": "Some Journal",
            "title": "x", "abstract": ""}
    better = dict(base, cited_by_count=5000, year=2001, author_countries=[["US"], ["DE"]],
                  venue="Applied Physics Letters", title="Organic light-emitting diode outcoupling")
    max_log = 9.0
    assert priority(better, max_log) > priority(base, max_log)
    assert priority(better, max_log) <= sum(PRIORITY_WEIGHTS.values()) + 1e-9


def test_abstract_reconstruction_and_holdout():
    assert _abstract({"light": [1], "Efficient": [0], "emission": [2]}) == "Efficient light emission"
    assert is_holdout("W123", 0.1) == is_holdout("W123", 0.1)


def test_review_and_topic_filters():
    rec = {"title": "25th Anniversary Article: Organic Field-Effect Transistors", "venue": "Advanced Materials", "abstract": ""}
    assert is_review(rec)
    assert not is_review({"title": "Bright LEDs", "venue": "Physical Review Letters"})
    assert not on_topic({"title": "Ultrafast all-optical switching by single photons", "abstract": ""})
    assert on_topic({"title": "High-efficiency red electrophosphorescence devices", "abstract": ""})
