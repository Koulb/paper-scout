# Paper Scout

Search for academic papers and store them in a local SQLite database. Papers are automatically deduplicated by title.

Current implementation queries **arXiv** and **Google Scholar**. Treat source selection, ranking, and filtering policy as controlled by the latest instructions in the *paper-clib* chat, not by this README.

## Installation

```bash
pip install arxiv scholarly
```

Database-only commands work without those packages installed. Search commands need the relevant provider packages.

## Usage

```bash
# Show database statistics
python search.py

# Search for papers
python search.py "electron-phonon coupling beyond DFT"

# Search with more results per source
python search.py "GW quasiparticle" -n 10

# List all papers in the database
python search.py --inspect-database

# Remove an irrelevant paper by its ID
python search.py --remove <paper-id>

# Use a custom database path
python search.py --db /path/to/papers.db "query"
```

## Running tests

```bash
pip install pytest
pytest test_search.py -v
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
