"""Reference verification against CrossRef (RULES.md 3.5): catches hallucinated citations."""
from __future__ import annotations

import re
import time
from difflib import SequenceMatcher

import requests

from .models import ReferenceCheck

CROSSREF = "https://api.crossref.org/works"
_DOI = re.compile(r"\b(10\.\d{4,9}/[^\s\"<>]+)", re.I)


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", s.lower())


def _similar(a: str, b: str) -> float:
    return SequenceMatcher(None, _norm(a), _norm(b)).ratio()


def _session(mailto: str | None) -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = "humanizer/0.1" + (f" (mailto:{mailto})" if mailto else "")
    return s


def check_references(refs: list[str], mailto: str | None = None, delay: float = 0.2,
                     timeout: float = 20.0) -> list[ReferenceCheck]:
    session = _session(mailto)
    out: list[ReferenceCheck] = []
    for i, ref in enumerate(refs):
        m = _DOI.search(ref)
        doi = m.group(1).rstrip(".,;)") if m else None
        try:
            if doi:
                r = session.get(f"{CROSSREF}/{doi}", timeout=timeout)
                if r.status_code == 404:
                    out.append(ReferenceCheck(i, ref, doi, "doi_not_found", "CrossRef에 없는 DOI (AI 환각 인용 의심)"))
                elif r.ok:
                    title = " ".join(r.json()["message"].get("title", []))
                    # The reference string contains authors/journal too, so compare title against it loosely.
                    if title and _similar(title, ref) < 0.3 and _norm(title)[:40] not in _norm(ref):
                        out.append(ReferenceCheck(i, ref, doi, "title_mismatch", f"DOI의 실제 제목: {title}"))
                    else:
                        out.append(ReferenceCheck(i, ref, doi, "ok"))
                else:
                    out.append(ReferenceCheck(i, ref, doi, "error", f"HTTP {r.status_code}"))
            else:
                r = session.get(CROSSREF, params={"query.bibliographic": ref[:300], "rows": 1}, timeout=timeout)
                items = r.json().get("message", {}).get("items", []) if r.ok else []
                if not r.ok:
                    out.append(ReferenceCheck(i, ref, None, "error", f"HTTP {r.status_code}"))
                elif items and items[0].get("score", 0) >= 60:
                    found = items[0]
                    title = " ".join(found.get("title", []))
                    out.append(ReferenceCheck(i, ref, found.get("DOI"), "ok", f"추정 일치: {title}"))
                else:
                    out.append(ReferenceCheck(i, ref, None, "no_match", "CrossRef 서지 검색에서 확실한 일치 없음"))
        except requests.RequestException as e:
            out.append(ReferenceCheck(i, ref, doi, "error", str(e)[:200]))
        time.sleep(delay)
    return out
