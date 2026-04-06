"""Search Google Scholar for papers."""

from scholarly import scholarly


def search_scholar(query: str, num_results: int = 5) -> list[dict]:
    """Search for papers on Google Scholar.

    Returns a list of dicts with keys: title, authors, year, abstract, url, venue, citations.
    """
    results = []
    count = 0

    for pub in scholarly.search_pubs(query):
        if count >= num_results:
            break
        bib = pub.get("bib", {})
        results.append({
            "title": bib.get("title", ""),
            "authors": bib.get("author", []),
            "year": bib.get("pub_year"),
            "venue": bib.get("journal", "") or bib.get("booktitle", ""),
            "citations": pub.get("num_citations", 0),
            "url": pub.get("pub_url", ""),
            "abstract": (bib.get("abstract") or "")[:500],
        })
        count += 1

    return results
