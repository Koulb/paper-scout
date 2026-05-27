"""Fetch citation counts and author h-indices from Semantic Scholar.

Uses the free public API (no key required, 100 req/min).
All calls are throttled and fail silently so a bad network day never
blocks the main pipeline.
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request

S2_BASE = "https://api.semanticscholar.org/graph/v1"
_MIN_INTERVAL_SEC = 0.7  # ~85 req/min — safely under the 100/min free limit
_last_request_at = 0.0


def _throttle() -> None:
    global _last_request_at
    now = time.monotonic()
    wait = _MIN_INTERVAL_SEC - (now - _last_request_at)
    if wait > 0:
        time.sleep(wait)
    _last_request_at = time.monotonic()


def _get(url: str, timeout: int = 10) -> dict | None:
    _throttle()
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "PaperScout/1.0 (research tool)"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def _arxiv_id_from_candidate_id(candidate_id: str) -> str | None:
    """Extract bare arXiv ID (no version) from a candidate id like 'arx-2605.26179v1'."""
    if not candidate_id.startswith("arx-"):
        return None
    raw = candidate_id[4:]  # e.g. "2605.26179v1"
    return raw.split("v")[0]  # e.g. "2605.26179"


def fetch_paper_metrics(candidate_id: str, title: str | None = None) -> dict:
    """Return {citations: int|None, s2_authors: list[{authorId, name}]}.

    Tries arXiv ID lookup first, falls back to title search for non-arXiv papers.
    """
    data = None
    arxiv_id = _arxiv_id_from_candidate_id(candidate_id)

    if arxiv_id:
        data = _get(f"{S2_BASE}/paper/arXiv:{arxiv_id}?fields=citationCount,authors")

    if not data and title:
        encoded = urllib.parse.quote(title[:200])
        result = _get(
            f"{S2_BASE}/paper/search?query={encoded}&fields=citationCount,authors&limit=1"
        )
        if result and result.get("data"):
            data = result["data"][0]

    if not data:
        return {"citations": None, "s2_authors": []}

    return {
        "citations": data.get("citationCount"),
        "s2_authors": data.get("authors") or [],
    }


def fetch_author_hindex(author_id: str) -> int | None:
    """Return h-index for a single Semantic Scholar author ID."""
    data = _get(f"{S2_BASE}/author/{author_id}?fields=hIndex")
    if not data:
        return None
    h = data.get("hIndex")
    return int(h) if h is not None else None


def fetch_top_hindex(s2_authors: list[dict], n_last: int = 3) -> int | None:
    """Return the max h-index among the last *n_last* authors (typically the senior PIs)."""
    targets = s2_authors[-n_last:] if len(s2_authors) > n_last else s2_authors
    hindices = []
    for author in targets:
        author_id = author.get("authorId")
        if not author_id:
            continue
        h = fetch_author_hindex(author_id)
        if h is not None:
            hindices.append(h)
    return max(hindices) if hindices else None
