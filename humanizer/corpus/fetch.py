"""Download open-access full texts in the order of rule C4."""
from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path

import requests

log = logging.getLogger(__name__)
EUROPE_PMC = "https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML"


def _arxiv_pdf(url: str) -> str:
    m = re.search(r"arxiv\.org/(?:abs|pdf)/([^\s?#]+?)(?:v\d+)?(?:\.pdf)?$", url)
    return f"https://arxiv.org/pdf/{m.group(1)}" if m else url


def _get(session: requests.Session, url: str, want: str) -> bytes | None:
    try:
        r = session.get(url, timeout=60, allow_redirects=True)
    except requests.RequestException as e:
        log.info("fetch failed %s: %s", url, e)
        return None
    if not r.ok:
        log.info("HTTP %s for %s", r.status_code, url)
        return None
    body = r.content
    if want == "pdf" and not body.startswith(b"%PDF"):
        return None  # landing page, captcha or paywall: skip, never work around it
    if want == "xml" and b"<body" not in body:
        return None  # Europe PMC returned metadata only
    return body


def fetch_all(candidates: str | Path, raw_dir: str | Path, *, limit: int | None = None,
              mailto: str | None = None, delay: float = 1.0) -> dict[str, int]:
    raw = Path(raw_dir)
    raw.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers["User-Agent"] = "humanizer/0.1 (research corpus; " + (f"mailto:{mailto})" if mailto else "no contact)")
    stats = {"xml": 0, "pdf": 0, "skipped": 0, "cached": 0}
    log_path = raw / "fetch_log.jsonl"
    with open(candidates, encoding="utf-8") as fh, open(log_path, "a", encoding="utf-8") as logf:
        for n, line in enumerate(fh):
            if limit is not None and n >= limit:
                break
            rec = json.loads(line)
            wid = rec["id"]
            if (raw / f"{wid}.xml").exists() or (raw / f"{wid}.pdf").exists():
                stats["cached"] += 1
                continue
            attempts: list[tuple[str, str]] = []
            if rec.get("pmcid"):
                attempts.append((EUROPE_PMC.format(pmcid=rec["pmcid"]), "xml"))
            if rec.get("arxiv"):
                attempts.append((_arxiv_pdf(rec["arxiv"]), "pdf"))
            if rec.get("pdf_url"):
                attempts.append((rec["pdf_url"], "pdf"))
            saved = None
            for url, kind in attempts:
                body = _get(session, url, kind)
                time.sleep(delay)
                if body:
                    (raw / f"{wid}.{kind}").write_bytes(body)
                    saved = (url, kind)
                    break
            if saved:
                stats[saved[1]] += 1
            else:
                stats["skipped"] += 1
            logf.write(json.dumps({"id": wid, "saved": saved, "tried": [u for u, _ in attempts]}) + "\n")
    return stats
