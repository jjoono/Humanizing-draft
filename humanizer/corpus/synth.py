"""Build the AI contrast corpus (RULES.md C7) by having an LLM rewrite human paragraphs."""
from __future__ import annotations

import json
import logging
import random
from pathlib import Path

from ..profile import iter_corpus

log = logging.getLogger(__name__)

PROMPTS = {
    # Paired data: same technical content, AI wording.
    "rewrite": ("You are helping draft a research paper on {topic}. Rewrite the following paragraph from the "
                "{section} section so it reads as a polished, publication-ready paragraph. Keep all technical "
                "content.\n\n{paragraph}"),
    # What a typical first AI draft looks like when given only the gist.
    "generate": ("Write the {section} paragraph of a research paper titled \"{title}\". The paragraph should cover "
                 "the following points:\n\n{paragraph}"),
}


def synthesize(human_path: str | Path, out_path: str | Path, *, mode: str = "rewrite", per_doc: int = 4,
               limit_docs: int | None = None, model: str = "claude-opus-5-5", seed: int = 0) -> int:
    import anthropic  # optional dependency

    client = anthropic.Anthropic()
    rng = random.Random(seed)
    written = 0
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "a", encoding="utf-8") as out:
        for n, doc in enumerate(iter_corpus(human_path)):
            if limit_docs is not None and n >= limit_docs:
                break
            pool = [(s["section"], p) for s in doc["sections"] if s["section"] != "caption" for p in s["paragraphs"]]
            sections: dict[str, list[str]] = {}
            for section, para in rng.sample(pool, min(per_doc, len(pool))):
                topic = ", ".join(doc.get("meta", {}).get("domains") or ["optoelectronic devices"])
                prompt = PROMPTS[mode].format(topic=topic, section=section, paragraph=para,
                                              title=doc.get("meta", {}).get("title") or "")
                try:
                    resp = client.beta.messages.create(
                        model=model, max_tokens=4000,
                        messages=[{"role": "user", "content": prompt}],
                        output_config={"effort": "low"},
                        betas=["server-side-fallback-2026-07-01"], fallbacks="default",
                    )
                except (anthropic.APIStatusError, anthropic.APIConnectionError) as e:
                    log.warning("skipping paragraph of %s: %s", doc["id"], e)
                    continue
                if resp.stop_reason == "refusal":
                    continue
                text = next((b.text for b in resp.content if b.type == "text"), "").strip()
                if text:
                    sections.setdefault(section, []).append(text)
            if sections:
                out.write(json.dumps({
                    "id": f"{doc['id']}-ai-{mode}", "source_id": doc["id"], "meta": {"model": model, "mode": mode},
                    "sections": [{"section": k, "paragraphs": v} for k, v in sections.items()],
                }, ensure_ascii=False) + "\n")
                written += 1
    return written
