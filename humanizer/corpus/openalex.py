"""Find and rank candidate papers via the OpenAlex API (RULES.md C1-C3)."""
from __future__ import annotations

import json
import logging
import math
import time
from pathlib import Path
from typing import Iterator

import requests

from .. import config

log = logging.getLogger(__name__)
API = "https://api.openalex.org/works"
SELECT = ",".join([
    "id", "doi", "title", "publication_year", "cited_by_count", "authorships", "primary_location",
    "best_oa_location", "open_access", "ids", "abstract_inverted_index", "language", "type",
])


def _abstract(inv: dict | None) -> str:
    if not inv:
        return ""
    pos = sorted((i, w) for w, idx in inv.items() for i in idx)
    return " ".join(w for _, w in pos)


def search(query: str, *, max_results: int, mailto: str | None, countries_only: bool,
           session: requests.Session) -> Iterator[dict]:
    filters = [
        f"publication_year:{config.YEAR_MIN}-{config.YEAR_MAX}",
        "is_oa:true",
        "type:article",
        "language:en",
        f"title_and_abstract.search:{query}",
    ]
    if countries_only:
        filters.append("authorships.institutions.country_code:" + "|".join(sorted(config.PRIORITY_COUNTRIES)))
    params = {"filter": ",".join(filters), "sort": "cited_by_count:desc", "per-page": 200,
              "cursor": "*", "select": SELECT}
    if mailto:
        params["mailto"] = mailto
    got = 0
    while got < max_results:
        r = session.get(API, params=params, timeout=60)
        r.raise_for_status()
        data = r.json()
        for w in data.get("results", []):
            yield w
            got += 1
            if got >= max_results:
                return
        cursor = data.get("meta", {}).get("next_cursor")
        if not cursor or not data.get("results"):
            return
        params["cursor"] = cursor
        time.sleep(0.2)


def _record(w: dict, domain: str) -> dict:
    authors = w.get("authorships") or []
    countries = [sorted({i.get("country_code") for i in a.get("institutions", []) if i.get("country_code")})
                 for a in authors]
    institutions = sorted({i.get("display_name") for a in authors for i in a.get("institutions", []) if i.get("display_name")})
    loc = w.get("best_oa_location") or {}
    prim = w.get("primary_location") or {}
    ids = w.get("ids") or {}
    return {
        "id": w["id"].rsplit("/", 1)[-1],
        "doi": w.get("doi"),
        "title": w.get("title") or "",
        "year": w.get("publication_year"),
        "cited_by_count": w.get("cited_by_count") or 0,
        "venue": ((prim.get("source") or {}).get("display_name")) or "",
        "author_countries": countries,
        "institutions": institutions,
        "pmcid": (ids.get("pmcid") or "").rsplit("/", 1)[-1] or None,
        "oa_status": (w.get("open_access") or {}).get("oa_status"),
        "pdf_url": loc.get("pdf_url"),
        "landing_url": loc.get("landing_page_url"),
        "license": loc.get("license"),
        "arxiv": next((l.get("landing_page_url") for l in [loc, prim] if "arxiv.org" in (l.get("landing_page_url") or "")), None),
        "abstract": _abstract(w.get("abstract_inverted_index")),
        "domains": [domain],
    }


def priority(rec: dict, max_log_cit: float) -> float:
    """Rule C3 priority score in [0, ~1.05]."""
    wts = config.PRIORITY_WEIGHTS
    cit = math.log1p(rec["cited_by_count"]) / max_log_cit if max_log_cit else 0.0
    age = min(1.0, max(0.0, (config.YEAR_MAX - (rec["year"] or config.YEAR_MAX)) / config.AGE_SPAN))
    per_author = [bool(set(c) & config.PRIORITY_COUNTRIES) for c in rec["author_countries"] if c]
    aff = sum(per_author) / len(per_author) if per_author else 0.0
    if per_author and per_author[-1]:
        aff = min(1.0, aff + config.LAST_AUTHOR_BONUS)
    venue = 1.0 if any(v in rec["venue"].lower() for v in config.PRIORITY_VENUES) else 0.0
    text = (rec["title"] + " " + rec["abstract"]).lower()
    topic = min(1.0, sum(t in text for t in config.TOPIC_TERMS) / 4)
    return round(wts["citations"] * cit + wts["age"] * age + wts["affiliation"] * aff
                 + wts["venue"] * venue + wts["topic"] * topic, 4)


def collect(out_path: str | Path, *, per_query: int = 200, mailto: str | None = None,
            domains: list[str] | None = None, countries_only: bool = True) -> int:
    """Run all domain queries, dedupe, score and write candidates sorted by priority."""
    session = requests.Session()
    session.headers["User-Agent"] = "humanizer/0.1" + (f" (mailto:{mailto})" if mailto else "")
    records: dict[str, dict] = {}
    for domain, queries in config.DOMAIN_QUERIES.items():
        if domains and domain not in domains:
            continue
        for q in queries:
            log.info("OpenAlex: %s / %s", domain, q)
            try:
                for w in search(q, max_results=per_query, mailto=mailto, countries_only=countries_only, session=session):
                    rec = _record(w, domain)
                    if rec["id"] in records:
                        if domain not in records[rec["id"]]["domains"]:
                            records[rec["id"]]["domains"].append(domain)
                    else:
                        records[rec["id"]] = rec
            except requests.RequestException as e:
                log.warning("query failed (%s): %s", q, e)
    max_log = max((math.log1p(r["cited_by_count"]) for r in records.values()), default=0.0)
    for r in records.values():
        r["priority"] = priority(r, max_log)
    ranked = sorted(records.values(), key=lambda r: -r["priority"])
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        for r in ranked:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    return len(ranked)
