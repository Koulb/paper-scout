"""Search arXiv for papers."""


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

    client = Client()
    search = Search(
        query=query,
        max_results=max_results,
        sort_by=SortCriterion.Relevance,
        sort_order=SortOrder.Descending,
    )

    results = []
    try:
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
