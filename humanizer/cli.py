"""Command-line interface: `humanizer <command>` (or `python -m humanizer`)."""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

DATA = Path("data")
CANDIDATES = DATA / "corpus" / "candidates.jsonl"
RAW = DATA / "raw"
HUMAN = DATA / "corpus" / "human_docs.jsonl"
HUMAN_TEST = DATA / "corpus" / "human_test.jsonl"
AI = DATA / "corpus" / "ai_docs.jsonl"
PROFILE = DATA / "profile" / "profile.json"
LEARNED = DATA / "profile" / "learned_markers.json"


def _mailto(args) -> str | None:
    return getattr(args, "mailto", None) or os.environ.get("HUMANIZER_MAILTO")


def cmd_collect(args) -> None:
    from .corpus.openalex import collect
    n = collect(args.out, per_query=args.per_query, mailto=_mailto(args), domains=args.domain,
                countries_only=not args.all_countries, api_key=args.api_key or os.environ.get("OPENALEX_API_KEY"))
    print(f"{n} candidates -> {args.out}")


def cmd_fetch(args) -> None:
    from .corpus.fetch import fetch_all
    print(fetch_all(args.candidates, args.raw, limit=args.limit, mailto=_mailto(args), delay=args.delay))


def cmd_extract(args) -> None:
    from .corpus.extract import extract_all
    print(extract_all(args.candidates, args.raw, args.out, args.test_out, holdout=args.holdout))


def cmd_build_profile(args) -> None:
    from .profile import build_profile, iter_corpus
    prof = build_profile(iter_corpus(args.corpus))
    prof.save(args.out)
    print(f"profile: {prof.documents} docs, {prof.total_words} words, sections={sorted(prof.sections)} -> {args.out}")


def cmd_synth_ai(args) -> None:
    from .corpus.synth import synthesize
    n = synthesize(args.corpus, args.out, mode=args.mode, per_doc=args.per_doc, limit_docs=args.limit, model=args.model)
    print(f"{n} AI documents appended -> {args.out}")


def cmd_learn_markers(args) -> None:
    from .profile import iter_corpus, learn_markers
    markers = learn_markers(iter_corpus(args.human), iter_corpus(args.ai), z_min=args.z_min, top_k=args.top_k)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(markers, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(markers)} learned markers -> {args.out}")
    for m in markers[:20]:
        print(f"  {m['term']:<30} z={m['z']:<6} ai={m['ai_count']:<5} human={m['human_count']}")


def cmd_evaluate(args) -> None:
    from .detect import Detector, DetectorConfig
    from .evaluate import evaluate
    from .profile import StyleProfile
    prof = StyleProfile.load(args.profile) if Path(args.profile).exists() else None
    det = Detector(DetectorConfig.load(args.rules, args.learned), prof)
    print(json.dumps(evaluate(det, args.human, args.ai if args.ai and Path(args.ai).exists() else None), indent=2))


def cmd_analyze(args) -> None:
    from .pipeline import analyze_file, write_outputs
    result = analyze_file(
        args.manuscript, profile_path=args.profile, learned_path=args.learned, rules_path=args.rules,
        allow=args.allow, suggest=args.suggest, suggest_min_risk=args.min_risk, model=args.model,
        refcheck=args.refcheck, mailto=_mailto(args),
    )
    paths = write_outputs(result, args.out, min_risk=args.min_risk, formats=tuple(args.formats.split(",")))
    s = result.summary()
    rc = s["risk_counts"]
    print(f"sentences={s['sentences']} high={rc['high']} medium={rc['medium']} low={rc['low']} "
          f"document_risk_score={s['document_risk_score']}")
    for p in paths:
        print(f"  -> {p}")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="humanizer", description=__doc__)
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("collect", help="search OpenAlex for pre-2020 OA papers and rank them (C1-C3)")
    p.add_argument("--out", default=str(CANDIDATES))
    p.add_argument("--per-query", type=int, default=200)
    p.add_argument("--domain", action="append", choices=["oled", "peled", "qled", "optics_display"])
    p.add_argument("--all-countries", action="store_true", help="do not require a US/EU-affiliated author")
    p.add_argument("--mailto", help="contact e-mail for the API polite pool (or HUMANIZER_MAILTO)")
    p.add_argument("--api-key", help="OpenAlex API key (or OPENALEX_API_KEY); free at openalex.org")
    p.set_defaults(func=cmd_collect)

    p = sub.add_parser("fetch", help="download full texts in priority order (C4)")
    p.add_argument("--candidates", default=str(CANDIDATES))
    p.add_argument("--raw", default=str(RAW))
    p.add_argument("--limit", type=int)
    p.add_argument("--delay", type=float, default=1.0)
    p.add_argument("--mailto")
    p.set_defaults(func=cmd_fetch)

    p = sub.add_parser("extract", help="convert downloaded files into a sectioned corpus (C5, E1)")
    p.add_argument("--candidates", default=str(CANDIDATES))
    p.add_argument("--raw", default=str(RAW))
    p.add_argument("--out", default=str(HUMAN))
    p.add_argument("--test-out", default=str(HUMAN_TEST))
    p.add_argument("--holdout", type=float, default=0.1)
    p.set_defaults(func=cmd_extract)

    p = sub.add_parser("build-profile", help="learn the human style profile (section 2)")
    p.add_argument("--corpus", default=str(HUMAN))
    p.add_argument("--out", default=str(PROFILE))
    p.set_defaults(func=cmd_build_profile)

    p = sub.add_parser("synth-ai", help="generate the AI contrast corpus with Claude (C7)")
    p.add_argument("--corpus", default=str(HUMAN))
    p.add_argument("--out", default=str(AI))
    p.add_argument("--mode", choices=["rewrite", "generate"], default="rewrite")
    p.add_argument("--per-doc", type=int, default=4)
    p.add_argument("--limit", type=int, help="number of human documents to use")
    p.add_argument("--model", default="claude-opus-5-5")
    p.set_defaults(func=cmd_synth_ai)

    p = sub.add_parser("learn-markers", help="learn AI-skewed n-grams from human vs AI corpora (LEX_LEARNED)")
    p.add_argument("--human", default=str(HUMAN))
    p.add_argument("--ai", default=str(AI))
    p.add_argument("--out", default=str(LEARNED))
    p.add_argument("--z-min", type=float, default=3.0)
    p.add_argument("--top-k", type=int, default=300)
    p.set_defaults(func=cmd_learn_markers)

    p = sub.add_parser("evaluate", help="false-positive rate on held-out human text, recall on AI text (E1-E5)")
    p.add_argument("--human", default=str(HUMAN_TEST))
    p.add_argument("--ai")
    p.add_argument("--profile", default=str(PROFILE))
    p.add_argument("--learned", default=str(LEARNED))
    p.add_argument("--rules")
    p.set_defaults(func=cmd_evaluate)

    p = sub.add_parser("analyze", help="flag AI-sounding sentences in a .docx/.pdf manuscript")
    p.add_argument("manuscript")
    p.add_argument("--out", default="out")
    p.add_argument("--profile", default=str(PROFILE))
    p.add_argument("--learned", default=str(LEARNED))
    p.add_argument("--rules", help="custom detector.yaml")
    p.add_argument("--allow", action="append", help="word to never flag (repeatable)")
    p.add_argument("--min-risk", choices=["low", "medium", "high"], default="medium",
                   help="lowest risk to annotate and to send for suggestions")
    p.add_argument("--suggest", action="store_true", help="ask Claude for rewrites (sends flagged paragraphs to the API, E6)")
    p.add_argument("--model", help="Claude model id for --suggest (default claude-opus-5-5)")
    p.add_argument("--refcheck", action="store_true", help="verify references against CrossRef")
    p.add_argument("--formats", default="annotated,docx,pdf,json")
    p.add_argument("--mailto")
    p.set_defaults(func=cmd_analyze)

    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(levelname)s %(message)s")
    args.func(args)


if __name__ == "__main__":
    sys.exit(main())
