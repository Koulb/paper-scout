# Paper Scout Skill

Search for academic papers on **arXiv** and **Google Scholar** and store them in a local SQLite database.

## Installation

```bash
pip install arxiv scholarly
```

## Usage

Paper Scout runs as a Python CLI with three modes:

### 1. Database statistics (no arguments)

```bash
python search.py
```

Shows how many papers are in the database, broken down by source.

### 2. Search for papers

```bash
python search.py "electron-phonon coupling beyond DFT"
```

Searches both Google Scholar and arXiv for the given query. New papers are automatically deduplicated (by title hash) and saved to the database. Use `-n` to control results per source:

```bash
python search.py "GW quasiparticle" -n 10
```

### 3. Inspect the database

```bash
python search.py --inspect-database
```

Lists every paper in the database with title, authors, year, and URL.

### 4. Remove a paper

```bash
python search.py --remove <paper-id>
```

Removes an irrelevant paper from the database. Use `--inspect-database` first to find the paper ID.

### Custom database path

```bash
python search.py --db /path/to/papers.db "query"
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
