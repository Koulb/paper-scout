#!/usr/bin/env python3
"""Paper Scout - search for academic papers on arXiv and Google Scholar.

Usage:
    python search.py                     Show database statistics
    python search.py <query>             Search for papers matching the query
    python search.py --inspect-database  List all papers in the database
    python search.py --remove <id>       Remove a paper by its ID
"""

import argparse

from paper_scout.database import get_connection, count_papers, get_all_papers, save_paper, remove_paper
from paper_scout.arxiv_search import search_arxiv
from paper_scout.scholar_search import search_scholar


def cmd_stats(conn):
    """Print database statistics."""
    counts = count_papers(conn)
    print(f"Database: {counts['total']} papers")
    print(f"  Google Scholar: {counts['google_scholar']}")
    print(f"  arXiv:          {counts['arxiv']}")


def cmd_inspect(conn):
    """Print all papers in the database."""
    papers = get_all_papers(conn)
    if not papers:
        print("Database is empty.")
        return
    for i, p in enumerate(papers, 1):
        year = p["year"] or "n/a"
        authors = (p["authors"] or "")[:80]
        print(f"{i:4d}. [{year}] {p['title'][:90]}")
        print(f"       ID: {p['id']}")
        print(f"       Authors: {authors}")
        print(f"       URL: {p['url'] or 'n/a'}")
        print()


def cmd_remove(conn, paper_id: str):
    """Remove a paper from the database by its ID."""
    if remove_paper(conn, paper_id):
        print(f"Removed paper: {paper_id}")
    else:
        print(f"No paper found with ID: {paper_id}")


def paper_year_meets_minimum(paper: dict, min_year: int | None = None) -> bool:
    """Return True when a paper meets the minimum-year persistence filter."""
    if min_year is None:
        return True

    raw_year = paper.get("year")
    if raw_year is None:
        return False

    try:
        year = int(str(raw_year).strip())
    except (TypeError, ValueError):
        return False

    return year >= min_year


def cmd_search(conn, query: str, num_results: int = 5, min_year: int | None = None):
    """Search Google Scholar and arXiv, save new papers to the database."""
    added = 0
    skipped_by_year = 0

    print(f"Searching Google Scholar for: {query}")
    try:
        gs_papers = search_scholar(query, num_results=num_results)
        for p in gs_papers:
            if not paper_year_meets_minimum(p, min_year=min_year):
                skipped_by_year += 1
                continue
            if save_paper(conn, p):
                added += 1
                print(f"  + [{p.get('year', '?')}] {p['title'][:80]}")
    except Exception as e:
        print(f"  Google Scholar error: {e}")

    print(f"\nSearching arXiv for: {query}")
    try:
        arxiv_papers = search_arxiv(query, max_results=num_results)
        for p in arxiv_papers:
            if not paper_year_meets_minimum(p, min_year=min_year):
                skipped_by_year += 1
                continue
            if save_paper(conn, p):
                added += 1
                print(f"  + [{p.get('year', '?')}] {p['title'][:80]}")
    except Exception as e:
        print(f"  arXiv error: {e}")

    counts = count_papers(conn)
    if min_year is not None:
        print(f"\nSkipped {skipped_by_year} papers older than {min_year} or missing a usable year.")
    print(f"\nAdded {added} new papers. Database now has {counts['total']} papers.")
    return added


def main():
    parser = argparse.ArgumentParser(
        description="Paper Scout - search for academic papers on arXiv and Google Scholar."
    )
    parser.add_argument("query", nargs="*", help="Search query")
    parser.add_argument(
        "--inspect-database", action="store_true",
        help="List all papers in the database",
    )
    parser.add_argument(
        "-n", "--num-results", type=int, default=5,
        help="Number of results per source (default: 5)",
    )
    parser.add_argument(
        "--remove", metavar="ID",
        help="Remove a paper by its ID (shown in --inspect-database output)",
    )
    parser.add_argument(
        "--db", default=None,
        help="Path to SQLite database (default: data/papers.db)",
    )
    parser.add_argument(
        "--min-year", type=int, default=None,
        help="Only persist papers published in or after this year",
    )

    args = parser.parse_args()
    conn = get_connection(args.db)

    if args.remove:
        cmd_remove(conn, args.remove)
    elif args.inspect_database:
        cmd_inspect(conn)
    elif args.query:
        query = " ".join(args.query)
        cmd_search(conn, query, num_results=args.num_results, min_year=args.min_year)
    else:
        cmd_stats(conn)

    conn.close()


if __name__ == "__main__":
    main()
