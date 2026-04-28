#!/usr/bin/env python3
"""Test that paper-scout can find beyond-DFT papers."""

import importlib.util
import os
import tempfile
import unittest

from paper_scout.database import get_connection, count_papers, save_paper
from paper_scout.arxiv_search import search_arxiv


class TestDatabase(unittest.TestCase):
    """Test database operations with a temporary database."""

    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".db")
        self.conn = get_connection(self.db_path)

    def tearDown(self):
        self.conn.close()
        os.close(self.db_fd)
        os.unlink(self.db_path)

    def test_empty_database(self):
        counts = count_papers(self.conn)
        self.assertEqual(counts["total"], 0)

    def test_save_and_retrieve_paper(self):
        paper = {
            "title": "Electron-phonon coupling beyond DFT",
            "authors": ["A. Author", "B. Coauthor"],
            "year": 2025,
            "abstract": "We study electron-phonon coupling using GW.",
            "url": "https://example.com/paper1",
        }
        inserted = save_paper(self.conn, paper)
        self.assertTrue(inserted)
        counts = count_papers(self.conn)
        self.assertEqual(counts["total"], 1)

    def test_dedup_by_title(self):
        paper = {
            "title": "GW self-energy for phonons",
            "authors": ["X. Test"],
            "year": 2024,
            "url": "https://example.com/p2",
        }
        save_paper(self.conn, paper)
        inserted_again = save_paper(self.conn, paper)
        self.assertFalse(inserted_again)
        self.assertEqual(count_papers(self.conn)["total"], 1)


class TestArxivSearch(unittest.TestCase):
    """Test that arXiv search returns beyond-DFT papers."""

    @unittest.skipUnless(importlib.util.find_spec("arxiv"), "arxiv package not installed")
    def test_find_beyond_dft_papers(self):
        results = search_arxiv("electron-phonon coupling beyond DFT GW", max_results=5)
        self.assertGreater(len(results), 0, "arXiv search returned no results")

        # Check that results have the expected fields
        for paper in results:
            self.assertIn("title", paper)
            self.assertIn("authors", paper)
            self.assertIn("abstract", paper)

        # At least one result should mention electron-phonon or DFT or GW
        titles_and_abstracts = " ".join(
            (p["title"] + " " + p.get("abstract", "")).lower() for p in results
        )
        relevant_terms = ["electron-phonon", "phonon", "dft", "gw", "self-energy", "quasiparticle"]
        found = any(term in titles_and_abstracts for term in relevant_terms)
        self.assertTrue(found, f"No relevant terms found in results: {[p['title'] for p in results]}")


if __name__ == "__main__":
    unittest.main()
