"""SQLite database operations for paper storage and retrieval."""

import os
import sqlite3
from datetime import datetime
from typing import Any, Iterable

from paper_scout.normalize import compute_title_hash

SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB_PATH = os.path.join(SCRIPT_DIR, "data", "papers.db")

def get_connection(db_path: str | None = None) -> sqlite3.Connection:
    """Open a connection to the papers database, creating tables if needed."""
    path = db_path or DEFAULT_DB_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
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
            citations INTEGER,
            top_author_hindex INTEGER,
            s2_fetched_at TEXT,
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
        CREATE TABLE IF NOT EXISTS recommendation_runs (
            run_id TEXT PRIMARY KEY,
            started_at TEXT NOT NULL,
            completed_at TEXT NOT NULL,
            fresh_since TEXT,
            min_year INTEGER,
            report_count INTEGER NOT NULL,
            top_count INTEGER NOT NULL,
            search_minutes REAL NOT NULL,
            skip_search INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS recommendation_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            paper_id TEXT NOT NULL,
            rank INTEGER NOT NULL,
            was_fresh INTEGER NOT NULL DEFAULT 0,
            score INTEGER,
            recommended_at TEXT NOT NULL,
            FOREIGN KEY (run_id) REFERENCES recommendation_runs(run_id) ON DELETE CASCADE,
            FOREIGN KEY (paper_id) REFERENCES papers(id) ON DELETE CASCADE,
            UNIQUE (run_id, paper_id)
        );
        CREATE TABLE IF NOT EXISTS paper_feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            paper_id TEXT NOT NULL,
            slack_ts TEXT NOT NULL,
            run_id TEXT,
            thumbs_up INTEGER NOT NULL DEFAULT 0,
            thumbs_down INTEGER NOT NULL DEFAULT 0,
            fetched_at TEXT NOT NULL,
            FOREIGN KEY (paper_id) REFERENCES papers(id) ON DELETE CASCADE,
            UNIQUE(paper_id, slack_ts)
        );
        CREATE INDEX IF NOT EXISTS idx_papers_title_hash ON papers(title_hash);
        CREATE INDEX IF NOT EXISTS idx_recommendation_history_paper_id ON recommendation_history(paper_id);
        CREATE INDEX IF NOT EXISTS idx_recommendation_history_recommended_at ON recommendation_history(recommended_at DESC);
    """)
    # Idempotent column migrations for DBs created before these columns existed
    for col_def in [
        "ALTER TABLE papers ADD COLUMN citations INTEGER",
        "ALTER TABLE papers ADD COLUMN top_author_hindex INTEGER",
        "ALTER TABLE papers ADD COLUMN s2_fetched_at TEXT",
        "ALTER TABLE papers ADD COLUMN posted_at TEXT",
        "ALTER TABLE recommendation_history ADD COLUMN slack_ts TEXT",
    ]:
        try:
            conn.execute(col_def)
        except sqlite3.OperationalError:
            pass  # column already exists
    conn.commit()


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


def update_paper_metrics(
    conn: sqlite3.Connection,
    paper_id: str,
    *,
    citations: int | None,
    top_author_hindex: int | None,
) -> None:
    """Persist Semantic Scholar metrics so they survive across runs."""
    conn.execute(
        "UPDATE papers SET citations=?, top_author_hindex=?, s2_fetched_at=? WHERE id=?",
        (citations, top_author_hindex, datetime.now().isoformat(), paper_id),
    )
    conn.commit()


def mark_papers_posted(conn: sqlite3.Connection, paper_ids: list[str]) -> None:
    """Stamp posted_at on papers that were just sent to Slack."""
    now = datetime.now().isoformat()
    conn.executemany(
        "UPDATE papers SET posted_at = ? WHERE id = ? AND posted_at IS NULL",
        [(now, pid) for pid in paper_ids],
    )
    conn.commit()


def get_posted_paper_ids(conn: sqlite3.Connection) -> set[str]:
    """Return IDs of all papers that have been posted to Slack."""
    rows = conn.execute("SELECT id FROM papers WHERE posted_at IS NOT NULL").fetchall()
    return {row["id"] for row in rows}


def get_posted_urls(conn: sqlite3.Connection) -> set[str]:
    """Return URLs of all papers that have been posted to Slack."""
    rows = conn.execute("SELECT url FROM papers WHERE posted_at IS NOT NULL AND url != ''").fetchall()
    return {row["url"] for row in rows}


def mark_posted_by_urls(conn: sqlite3.Connection, urls: set[str]) -> int:
    """Mark papers as posted by matching their stored URL against a set of canonical URLs.

    Returns number of rows updated.
    """
    if not urls:
        return 0
    now = datetime.now().isoformat()
    updated = 0
    for url in urls:
        cursor = conn.execute(
            "UPDATE papers SET posted_at = ? WHERE url = ? AND posted_at IS NULL",
            (now, url),
        )
        updated += cursor.rowcount
    conn.commit()
    return updated


def remove_paper(conn: sqlite3.Connection, paper_id: str) -> bool:
    """Remove a paper by its ID. Returns True if a row was deleted."""
    cursor = conn.execute("DELETE FROM papers WHERE id = ?", (paper_id,))
    conn.commit()
    return cursor.rowcount > 0


def recommendation_history_count(conn: sqlite3.Connection) -> int:
    """Return how many recommendation-history rows exist."""
    return conn.execute("SELECT COUNT(*) FROM recommendation_history").fetchone()[0]


def get_last_recommendation_at(conn: sqlite3.Connection) -> str | None:
    """Return the completion timestamp of the most recent successful recommendation run."""
    row = conn.execute(
        "SELECT completed_at FROM recommendation_runs ORDER BY completed_at DESC LIMIT 1"
    ).fetchone()
    if not row:
        return None
    return row["completed_at"]


def save_paper_slack_ts(conn: sqlite3.Connection, paper_id: str, run_id: str, slack_ts: str) -> None:
    """Store the Slack message ts for a recommended paper so reactions can be read back later."""
    conn.execute(
        "UPDATE recommendation_history SET slack_ts = ? WHERE paper_id = ? AND run_id = ?",
        (slack_ts, paper_id, run_id),
    )
    conn.commit()


def get_unread_posted_messages(conn: sqlite3.Connection) -> list:
    """Return recommendation_history rows that have a slack_ts but no feedback record yet."""
    return conn.execute("""
        SELECT rh.paper_id, rh.run_id, rh.slack_ts,
               p.title, p.url
        FROM recommendation_history rh
        JOIN papers p ON p.id = rh.paper_id
        WHERE rh.slack_ts IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM paper_feedback pf
              WHERE pf.paper_id = rh.paper_id AND pf.slack_ts = rh.slack_ts
          )
    """).fetchall()


def save_paper_feedback(
    conn: sqlite3.Connection,
    paper_id: str,
    slack_ts: str,
    run_id: str | None,
    thumbs_up: int,
    thumbs_down: int,
    fetched_at: str | None = None,
) -> None:
    now = fetched_at or datetime.now().isoformat()
    conn.execute(
        """INSERT OR REPLACE INTO paper_feedback
           (paper_id, slack_ts, run_id, thumbs_up, thumbs_down, fetched_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (paper_id, slack_ts, run_id, thumbs_up, thumbs_down, now),
    )
    conn.commit()


def _paper_value(paper: Any, key: str, default=None):
    if isinstance(paper, dict):
        return paper.get(key, default)
    return getattr(paper, key, default)


def record_recommendation_run(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    started_at: str,
    completed_at: str,
    fresh_since: str | None,
    min_year: int,
    report_count: int,
    top_count: int,
    search_minutes: float,
    skip_search: bool,
    papers: Iterable[Any],
) -> None:
    """Persist a successful recommendation run and the papers it surfaced."""
    conn.execute(
        """
        INSERT OR REPLACE INTO recommendation_runs
        (run_id, started_at, completed_at, fresh_since, min_year, report_count, top_count, search_minutes, skip_search)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            started_at,
            completed_at,
            fresh_since,
            min_year,
            report_count,
            top_count,
            search_minutes,
            1 if skip_search else 0,
        ),
    )

    rows = []
    for rank, paper in enumerate(papers, 1):
        paper_id = _paper_value(paper, "id")
        if not paper_id:
            continue
        rows.append(
            (
                run_id,
                paper_id,
                rank,
                1 if _paper_value(paper, "new_today", False) else 0,
                _paper_value(paper, "score"),
                completed_at,
            )
        )

    if rows:
        conn.executemany(
            """
            INSERT OR IGNORE INTO recommendation_history
            (run_id, paper_id, rank, was_fresh, score, recommended_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            rows,
        )

    conn.commit()
