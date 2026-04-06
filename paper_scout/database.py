"""SQLite database operations for paper storage and retrieval."""

import os
import sqlite3
from datetime import datetime
from paper_scout.normalize import compute_title_hash

SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB_PATH = os.path.join(SCRIPT_DIR, "data", "papers.db")

def get_connection(db_path: str | None = None) -> sqlite3.Connection:
    """Open a connection to the papers database, creating tables if needed."""
    path = db_path or DEFAULT_DB_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    _ensure_schema(conn)
    return conn


def _ensure_schema(conn: sqlite3.Connection):
    """Create tables if they don't exist."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS papers (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            authors TEXT NOT NULL,
            year INTEGER,
            abstract TEXT,
            url TEXT,
            doi TEXT,
            arxiv_id TEXT,
            journal TEXT,
            title_hash TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS evaluations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            paper_id TEXT NOT NULL,
            evaluation_version TEXT NOT NULL,
            decision TEXT NOT NULL CHECK(decision IN ('relevant', 'irrelevant', 'uncertain')),
            score REAL NOT NULL CHECK(score >= 0 AND score <= 1),
            why_relevant TEXT,
            summary_bullets TEXT,
            uncertainty TEXT,
            evaluated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (paper_id) REFERENCES papers(id) ON DELETE CASCADE
        );
    """)


def count_papers(conn: sqlite3.Connection) -> dict:
    """Return paper counts by source."""
    total = conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
    gs = conn.execute("SELECT COUNT(*) FROM papers WHERE id LIKE 'gs-%'").fetchone()[0]
    arxiv = conn.execute("SELECT COUNT(*) FROM papers WHERE id LIKE 'arx-%'").fetchone()[0]
    return {"total": total, "google_scholar": gs, "arxiv": arxiv}


def get_all_papers(conn: sqlite3.Connection) -> list[dict]:
    """Return all papers as a list of dicts."""
    rows = conn.execute(
        "SELECT id, title, authors, year, abstract, url, doi, arxiv_id, journal, created_at "
        "FROM papers ORDER BY created_at DESC"
    ).fetchall()
    return [dict(row) for row in rows]


def save_paper(conn: sqlite3.Connection, paper: dict) -> bool:
    """Insert a paper if it doesn't already exist (dedup by title hash).

    Returns True if the paper was newly inserted.
    """
    title = paper.get("title", "")
    if not title:
        return False

    title_hash = compute_title_hash(title)

    # Check for duplicate
    existing = conn.execute("SELECT id FROM papers WHERE title_hash = ?", (title_hash,)).fetchone()
    if existing:
        return False

    # Normalize authors
    authors_data = paper.get("authors", [])
    if isinstance(authors_data, list):
        authors = "; ".join(str(a) for a in authors_data)
    else:
        authors = str(authors_data)

    url = paper.get("url", "")
    year = None
    raw_year = paper.get("year")
    if raw_year and str(raw_year).isdigit():
        year = int(raw_year)

    # Generate a unique ID based on source
    arxiv_id = paper.get("arxiv_id", "")
    if arxiv_id or url.startswith("http://arxiv.org") or url.startswith("https://arxiv.org"):
        paper_id = f"arx-{arxiv_id or url.split('/')[-1]}"[:64]
    else:
        paper_id = f"gs-{title_hash[:24]}"

    conn.execute(
        "INSERT OR IGNORE INTO papers "
        "(id, title, authors, year, abstract, url, doi, arxiv_id, journal, title_hash, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            paper_id,
            title[:500],
            authors[:2000],
            year,
            (paper.get("abstract") or "")[:3000],
            url[:500],
            paper.get("doi", ""),
            arxiv_id,
            paper.get("venue", "") or paper.get("journal", ""),
            title_hash,
            datetime.now().isoformat(),
        ),
    )
    conn.commit()
    return True


def remove_paper(conn: sqlite3.Connection, paper_id: str) -> bool:
    """Remove a paper by its ID. Returns True if a row was deleted."""
    cursor = conn.execute("DELETE FROM papers WHERE id = ?", (paper_id,))
    conn.commit()
    return cursor.rowcount > 0
