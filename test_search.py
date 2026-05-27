#!/usr/bin/env python3
"""Test that paper-scout can find beyond-DFT papers."""

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path

from search import paper_year_meets_minimum
from run_paper_scout import Candidate, bootstrap_recommendation_history_from_latest_payload, build_why_read, fetch_candidates, score_candidate, select_takeaway
from paper_scout.database import count_papers, get_connection, get_last_recommendation_at, record_recommendation_run, recommendation_history_count, save_paper
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

    def test_min_year_filter(self):
        self.assertTrue(paper_year_meets_minimum({"year": 2024}, min_year=2024))
        self.assertTrue(paper_year_meets_minimum({"year": "2025"}, min_year=2024))
        self.assertFalse(paper_year_meets_minimum({"year": 2023}, min_year=2024))
        self.assertFalse(paper_year_meets_minimum({"year": None}, min_year=2024))
        self.assertTrue(paper_year_meets_minimum({"year": None}, min_year=None))

    def test_recommendation_history_excludes_already_shown_papers(self):
        paper1 = {
            "title": "AgentDFT: A Multi-Agent Framework for Automated DFT Workflows",
            "authors": ["A. Author"],
            "year": 2026,
            "abstract": "Agentic DFT workflow automation.",
            "url": "https://arxiv.org/abs/2603.03372v2",
        }
        paper2 = {
            "title": "ChatMat: A Multi-Agent Chemist for Autonomous Material Prediction and Exploration",
            "authors": ["B. Author"],
            "year": 2026,
            "abstract": "Autonomous materials discovery with agent orchestration.",
            "url": "https://arxiv.org/abs/2605.00001",
        }
        save_paper(self.conn, paper1)
        save_paper(self.conn, paper2)

        all_candidates = fetch_candidates(self.conn, min_year=2024, exclude_recommended=True)
        self.assertEqual({candidate.title for candidate in all_candidates}, {paper1["title"], paper2["title"]})

        shown = next(candidate for candidate in all_candidates if candidate.title == paper1["title"])
        record_recommendation_run(
            self.conn,
            run_id="run-1",
            started_at="2026-05-06T18:00:00+00:00",
            completed_at="2026-05-06T18:05:00+00:00",
            fresh_since="2026-05-06T17:00:00+00:00",
            min_year=2024,
            report_count=1,
            top_count=1,
            search_minutes=9.0,
            skip_search=False,
            papers=[shown],
        )

        remaining = fetch_candidates(self.conn, min_year=2024, exclude_recommended=True)
        self.assertEqual([candidate.title for candidate in remaining], [paper2["title"]])
        self.assertEqual(recommendation_history_count(self.conn), 1)
        self.assertEqual(get_last_recommendation_at(self.conn), "2026-05-06T18:05:00+00:00")

    def test_bootstrap_recommendation_history_from_latest_payload(self):
        paper = {
            "title": "DREAMS: Density functional theory based research engine for agentic materials simulation",
            "authors": ["C. Author"],
            "year": 2025,
            "abstract": "Hierarchical multi-agent DFT automation.",
            "url": "https://arxiv.org/abs/2507.14267",
        }
        save_paper(self.conn, paper)

        with tempfile.TemporaryDirectory() as tmpdir:
            payload_path = os.path.join(tmpdir, "latest_recommendation.json")
            with open(payload_path, "w", encoding="utf-8") as fh:
                json.dump(
                    {
                        "ran_at": "2026-05-06T18:01:48.118507+00:00",
                        "fresh_since": "2026-05-06T18:01:28.194508+00:00",
                        "min_year": 2024,
                        "report_ids": ["arx-2507.14267"],
                        "report_candidates": [{"id": "arx-2507.14267", "score": 10, "new_today": False}],
                    },
                    fh,
                )

            bootstrapped = bootstrap_recommendation_history_from_latest_payload(self.conn, Path(payload_path))

        self.assertTrue(bootstrapped)
        self.assertEqual(recommendation_history_count(self.conn), 1)
        remaining = fetch_candidates(self.conn, min_year=2024, exclude_recommended=True)
        self.assertEqual(remaining, [])


class TestArxivSearch(unittest.TestCase):
    """Test that arXiv search returns beyond-DFT papers."""

    @unittest.skipUnless(importlib.util.find_spec("arxiv"), "arxiv package not installed")
    def test_find_beyond_dft_papers(self):
        try:
            results = search_arxiv("electron-phonon coupling beyond DFT GW", max_results=5)
        except Exception as exc:
            self.skipTest(f"arXiv unavailable or rate-limited: {exc}")
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


class TestRecommendationScoring(unittest.TestCase):
    def test_agentic_materials_dft_scores_high(self):
        candidate = Candidate(
            id="x",
            title="DREAMS: Density Functional Theory Based Research Engine for Agentic Materials Simulation",
            authors="A. Author",
            year=2025,
            abstract="Agentic workflow automation for DFT structure generation, convergence testing, HPC scheduling, and materials simulation.",
            url="https://arxiv.org/abs/2507.14267",
            journal="",
            created_at="2026-05-05T00:00:00",
            new_today=True,
        )
        scored = score_candidate(candidate)
        self.assertGreaterEqual(scored.score, 8)
        self.assertIn(scored.track, {"A", "A+B"})

    def test_irrelevant_domain_scores_low(self):
        candidate = Candidate(
            id="z",
            title="PediatricsGPT: Large Language Models as Chinese Medical Assistants for Pediatric Applications",
            authors="A. Author",
            year=2024,
            abstract="Large language model system for pediatric healthcare assistance.",
            url="https://arxiv.org/abs/2405.19266",
            journal="",
            created_at="2026-05-05T00:00:00",
            new_today=True,
        )
        scored = score_candidate(candidate)
        self.assertLessEqual(scored.score, 4)

    def test_agentic_dft_why_read_hits_agentic_branch(self):
        candidate = Candidate(
            id="ta",
            title="AgentDFT: A Multi-Agent Framework for Automated DFT Workflows",
            authors="A. Author",
            year=2026,
            abstract="Autonomous agent workflow for DFT task planning, execution, and simulation.",
            url="https://example.com/agentdft",
            journal="",
            created_at="2026-05-05T00:00:00",
            new_today=True,
        )
        why = build_why_read(candidate)
        self.assertIn("agentic DFT/workflow", why)

    def test_takeaway_skips_chopped_fragments(self):
        text = "and the complexity of establishing accurate machine learning models for multi-elemental Hamiltonian model trained on Hamiltonian matrices obtained from first-principles DFT"
        takeaway = select_takeaway(text)
        self.assertEqual(takeaway, "Conclusion unavailable; abstract suggests it is worth a closer read.")

    def test_takeaway_prefers_complete_sentence(self):
        text = "Short fragment. Using advanced electronic structure methods leads to a significantly improved description of electron mobilities in GaAs and results in a closer agreement with experimental results."
        takeaway = select_takeaway(text)
        self.assertIn("significantly improved description of electron mobilities", takeaway)


if __name__ == "__main__":
    unittest.main()
