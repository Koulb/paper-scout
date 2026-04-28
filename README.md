# Paper Scout

Search for academic papers and store them in a local SQLite database. Papers are automatically deduplicated by title.

Current implementation queries **arXiv** and **Google Scholar**. Treat source selection, ranking, and filtering policy as controlled by the latest instructions in the *paper-clib* chat, not by this README.

## Installation

```bash
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
```

Database-only commands work without those packages installed. Search commands need the relevant provider packages.

See `RECOMMENDATION_POLICY.md` for the standing paper-recommendation workflow and research tracks.

## Usage

```bash
# Show database statistics
./.venv/bin/python search.py

# Search for papers
./.venv/bin/python search.py "electron-phonon coupling beyond DFT"

# Search with more results per source
./.venv/bin/python search.py "GW quasiparticle" -n 10

# List all papers in the database
./.venv/bin/python search.py --inspect-database

# Remove an irrelevant paper by its ID
./.venv/bin/python search.py --remove <paper-id>

# Use a custom database path
./.venv/bin/python search.py --db /path/to/papers.db "query"
```

## Running tests

```bash
./.venv/bin/python test_search.py -v
```

## Project structure

```
search.py                  # CLI entry point
paper_scout/
  database.py              # SQLite operations (connect, save, query)
  arxiv_search.py          # arXiv API wrapper
  scholar_search.py        # Google Scholar wrapper
  normalize.py             # Title normalization and hashing for dedup
data/papers.db             # Default database location (created on first run)
```
