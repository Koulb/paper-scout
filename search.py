#!/usr/bin/env python3
"""Paper Scout - search for academic papers on arXiv and Google Scholar.

Usage:
    python search.py                     Show database statistics
    python search.py <query>             Search for papers matching the query
    python search.py --inspect-database  List all papers in the database
"""

import argparse

from paper_scout.database import get_connection, count_papers, get_all_papers, save_paper
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
        print(f"       Authors: {authors}")
        print(f"       URL: {p['url'] or 'n/a'}")
        print()


def cmd_search(conn, query: str, num_results: int = 5):
    """Search Google Scholar and arXiv, save new papers to the database."""
    added = 0

    print(f"Searching Google Scholar for: {query}")
    try:
        gs_papers = search_scholar(query, num_results=num_results)
        for p in gs_papers:
            if save_paper(conn, p):
                added += 1
                print(f"  + [{p.get('year', '?')}] {p['title'][:80]}")
    except Exception as e:
        print(f"  Google Scholar error: {e}")

    print(f"\nSearching arXiv for: {query}")
    try:
        arxiv_papers = search_arxiv(query, max_results=num_results)
        for p in arxiv_papers:
            if save_paper(conn, p):
                added += 1
                print(f"  + [{p.get('year', '?')}] {p['title'][:80]}")
    except Exception as e:
        print(f"  arXiv error: {e}")

    counts = count_papers(conn)
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
        "--db", default=None,
        help="Path to SQLite database (default: data/papers.db)",
    )

    args = parser.parse_args()
    conn = get_connection(args.db)

    if args.inspect_database:
        cmd_inspect(conn)
    elif args.query:
        query = " ".join(args.query)
        cmd_search(conn, query, num_results=args.num_results)
    else:
        cmd_stats(conn)

    conn.close()


if __name__ == "__main__":
    main()
