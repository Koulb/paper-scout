"""Search arXiv for papers."""

from __future__ import annotations

import time


ARXIV_MIN_INTERVAL_SEC = 3.5
_last_arxiv_request_started_at = 0.0


def _throttle_arxiv_requests() -> None:
    """Respect arXiv's low-rate API expectations across sequential queries."""
    global _last_arxiv_request_started_at

    now = time.monotonic()
    wait_for = ARXIV_MIN_INTERVAL_SEC - (now - _last_arxiv_request_started_at)
    if wait_for > 0:
        time.sleep(wait_for)
        now = time.monotonic()
    _last_arxiv_request_started_at = now


def search_arxiv(query: str, max_results: int = 5) -> list[dict]:
    """Search papers on arXiv.

    Returns a list of dicts with keys: title, authors, year, abstract, url, arxiv_id.
    """
    try:
        from arxiv import Client, Search, SortCriterion, SortOrder
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Missing dependency 'arxiv'. Install with: pip install arxiv"
        ) from exc

    client = Client(page_size=max_results, delay_seconds=ARXIV_MIN_INTERVAL_SEC, num_retries=3)
    search = Search(
        query=query,
        max_results=max_results,
        sort_by=SortCriterion.Relevance,
        sort_order=SortOrder.Descending,
    )

    results = []
    try:
        _throttle_arxiv_requests()
        for paper in client.results(search):
            year = None
            if paper.published:
                year = paper.published.year

            results.append({
                "title": paper.title,
                "authors": [a.name for a in paper.authors],
                "year": year,
                "abstract": (paper.summary or "")[:3000],
                "url": paper.entry_id,
                "arxiv_id": paper.entry_id.split("/")[-1] if paper.entry_id else "",
            })
    except Exception as exc:
        if "429" in str(exc):
            raise RuntimeError("arXiv rate-limited (HTTP 429). Retry later.") from exc
        raise

    return results
