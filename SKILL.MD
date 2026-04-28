# Paper Scout Skill

Search for academic papers and store them in a local SQLite database.

Current implementation can query **arXiv** and **Google Scholar**, but do **not** treat this file as the source of truth for search/ranking/filtering policy. Follow the latest instructions in the *paper-club* chat for paper-selection behavior.

## Installation

```bash
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
```

Database-only commands work without those packages installed. Search commands need the relevant provider packages.

See `RECOMMENDATION_POLICY.md` for the current standing recommendation funnel, research tracks, and daily output expectations.

## Usage

Paper Scout runs as a Python CLI with three modes:

### 1. Database statistics (no arguments)

```bash
./.venv/bin/python search.py
```

Shows how many papers are in the database, broken down by source.

### 2. Search for papers

```bash
./.venv/bin/python search.py "electron-phonon coupling beyond DFT"
```

Runs the current configured search workflow, saves new papers to the database, and deduplicates by title hash. Use `-n` to control results per source:

```bash
./.venv/bin/python search.py "GW quasiparticle" -n 10
```

### 3. Inspect the database

```bash
./.venv/bin/python search.py --inspect-database
```

Lists every paper in the database with title, authors, year, and URL.

### 4. Remove a paper

```bash
./.venv/bin/python search.py --remove <paper-id>
```

Removes an irrelevant paper from the database. Use `--inspect-database` first to find the paper ID.

### Custom database path

```bash
./.venv/bin/python search.py --db /path/to/papers.db "query"
```

## Project structure

```
paper-scout/
  search.py                  # CLI entry point
  paper_scout/
    __init__.py
    database.py              # SQLite operations (connect, save, query)
    arxiv_search.py          # arXiv API wrapper
    scholar_search.py        # Google Scholar wrapper
    normalize.py             # Title normalization and hashing for dedup
  data/papers.db             # Default database location
  test_search.py             # Tests
```

## For agents

Before doing topic-specific search/ranking/filtering work, check the latest instructions in the *paper-club* chat. If those instructions conflict with this file, the chat wins.

To find papers on a topic, run:

```bash
python search.py "<topic keywords>"
```

To check what's already been collected:

```bash
python search.py
python search.py --inspect-database
```

To remove irrelevant papers after reviewing:

```bash
python search.py --inspect-database   # find the paper ID
python search.py --remove <paper-id>  # remove it
```

Papers are deduplicated automatically -- running the same query twice won't create duplicates.
