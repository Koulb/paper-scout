#!/usr/bin/env python3
"""Run the daily Paper Scout recommendation workflow in one local command."""

from __future__ import annotations

# Scoring constants
PRIORITY_SCORE_MAX = 13.8   # empirical max; all raw priority scores are normalized to 0–10
PRIMARY_THRESHOLD = 8.0     # normalized threshold; fall back to FALLBACK_THRESHOLD when pool runs dry
FALLBACK_THRESHOLD = 7.0    # used when fewer than report_count papers pass PRIMARY_THRESHOLD

import argparse
import json
import re
import sys
import textwrap
import time
import warnings
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import requests
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

from paper_scout.arxiv_search import search_arxiv
from paper_scout.database import (
    get_connection,
    get_last_recommendation_at,
    get_posted_paper_ids,
    mark_papers_posted,
    record_recommendation_run,
    recommendation_history_count,
    save_paper,
    save_paper_slack_ts,
    update_paper_metrics,
)
from paper_scout.semantic_scholar import fetch_paper_metrics, fetch_top_hindex
from paper_scout.scholar_search import search_scholar
from paper_scout.slack_post import collect_feedback, post_message, post_report, sync_posted_papers

ROOT = Path(__file__).resolve().parent
DEFAULT_DB_PATH = ROOT / "data" / "papers.db"
DEFAULT_ANALYSIS_DIR = ROOT / "analysis"
USER_AGENT = "PaperScout/1.0 (+https://github.com/openclaw/openclaw)"
REQUEST_HEADERS = {"User-Agent": USER_AGENT}
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

QUERY_FAMILIES = [
    {"track": "A", "query": "autonomous scientific discovery agentic AI science"},
    {"track": "A", "query": "self-driving laboratory large language model agents"},
    {"track": "A", "query": "AI scientist multimodal science model research agent"},
    {"track": "A", "query": "computational materials science large language model agents"},
    {"track": "A", "query": "large language model density functional theory"},
    {"track": "A", "query": "exchange-correlation functional discovery"},
    {"track": "A", "query": "agentic DFT workflow materials discovery"},
    {"track": "A", "query": "materials discovery multi-agent simulation workflow"},
    # Category-scoped arXiv browsing — date-sorted to catch fresh papers; arxiv only
    {"track": "A", "query": 'cat:cond-mat.mtrl-sci AND (agent OR autonomous OR agentic OR "large language model")', "providers": ["arxiv"], "sort_by": "date"},
    {"track": "A", "query": 'cat:cond-mat.mes-hall AND (agent OR autonomous OR agentic OR "large language model")', "providers": ["arxiv"], "sort_by": "date"},
    {"track": "A", "query": 'cat:physics.chem-ph AND (agent OR autonomous OR agentic OR "large language model")', "providers": ["arxiv"], "sort_by": "date"},
    {"track": "A", "query": 'cat:cs.LG AND (materials OR "density functional" OR atomistic OR "computational chemistry")', "providers": ["arxiv"], "sort_by": "date"},
    {"track": "A", "query": 'cat:cs.AI AND (materials OR "density functional" OR atomistic OR "computational chemistry")', "providers": ["arxiv"], "sort_by": "date"},
]

KEYWORD_GROUPS: list[tuple[str, tuple[str, ...], float]] = [
    ("agentic", ("agentic", "autonomous", "multi-agent", "multi agent", "ai scientist", "self-driving", "closed-loop", "closed loop"), 2.5),
    ("llm", ("large language model", "large language models", "llm", "multimodal", "foundation model", "foundation models"), 1.5),
    ("science", ("scientific discovery", "ai for science", "science automation", "research workflow", "tool use", "tool-use", "laboratory", "lab automation", "experiment"), 1.5),
    ("materials", ("materials science", "materials discovery", "material property", "materials", "material", "perovskite", "alloy", "catalyst", "battery", "semiconductor"), 2.0),
    ("compmats", ("computational materials", "electronic structure", "density functional theory", " dft", "workflow", "simulation", "hpc", "atomistic"), 2.0),
    ("agent_arch", ("model context protocol", " mcp ", "composable", "skill-based", "tool registry", "agent harness", "reusable tool", "plugin"), 0.0),  # tracked for bonus; weight=0 here
    ("planning", ("planning", "planner", "orchestration", "tool execution", "toolchain"), 1.0),
    ("robotics", ("robot", "robotic", "synthesis"), 1.0),
]

NEGATIVE_TERMS = (
    "pediatric",
    "healthcare",
    "biomarker",
    "astronomical",
    "autonomous driving",
    "lane changing",
    "school",
    "education",
    "behavioral science",
    "climate",
    "racing",
    "self-driving scene",
    "lidar",
    "alpha factor",
    "financial risk",
    "geospatial",
    "order fulfillment",
    "warehouse",
    "rna-seq",
    "rna seq",
    "single-cell",
    "genomics",
    "gene expression",
)

TAKEAWAY_HINTS = (
    "achieve",
    "achieved",
    "improve",
    "improves",
    "improved",
    "reduce",
    "reduces",
    "reaches",
    "reach",
    "outperform",
    "outperforms",
    "speedup",
    "%",
    "x ",
    " x",
    "benchmark",
)

HEADING_PATTERNS = {
    "abstract": re.compile(r"\babstract\b", re.I),
    "conclusion": re.compile(r"\b(conclusion|conclusions|discussion|summary|outlook)\b", re.I),
}


@dataclass
class Candidate:
    id: str
    title: str
    authors: str
    year: int | None
    abstract: str
    url: str
    journal: str
    created_at: str
    new_today: bool
    score: int = 0
    track: str = ""
    keyword_hits: list[str] = field(default_factory=list)
    why_read: str = ""
    takeaway: str = ""
    abstract_excerpt: str = ""
    conclusion_excerpt: str = ""
    notes: list[str] = field(default_factory=list)
    repeat_recommendation: bool = False
    citations: int | None = None
    top_author_hindex: int | None = None
    normalized_priority: float = 0.0


@dataclass
class SearchEvent:
    query: str
    track: str
    provider: str
    considered: int
    added: int
    elapsed_sec: float
    error: str | None = None


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_now_iso() -> str:
    return utc_now().isoformat()


def parse_timestamp(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def sentence_split(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", normalize_space(text)) if s.strip()]


def paper_year_meets_minimum(paper: dict, min_year: int | None = None) -> bool:
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


def run_provider_query(*, conn, query: str, provider: str, num_results: int, min_year: int | None, sort_by: str = "relevance") -> tuple[int, int]:
    if provider == "arxiv":
        papers = search_arxiv(query, max_results=num_results, sort_by=sort_by)
    elif provider == "scholar":
        papers = search_scholar(query, num_results=num_results)
    else:
        raise ValueError(f"Unknown provider: {provider}")

    added = 0
    considered = 0
    for paper in papers:
        considered += 1
        if not paper_year_meets_minimum(paper, min_year=min_year):
            continue
        if save_paper(conn, paper):
            added += 1
    return considered, added


def fetch_candidates(
    conn,
    *,
    min_year: int,
    created_since: datetime | None = None,
    exclude_ids: set[str] | None = None,
    exclude_recommended: bool = False,
    exclude_posted: bool = True,
) -> list[Candidate]:
    exclude_ids = exclude_ids or set()
    query = """
        SELECT p.id, p.title, p.authors, p.year, p.abstract, p.url, p.journal,
               p.created_at, p.citations, p.top_author_hindex
        FROM papers p
        WHERE p.year >= ?
    """
    if exclude_posted:
        query += " AND p.posted_at IS NULL\n"
    if exclude_recommended:
        query += """
        AND NOT EXISTS (
            SELECT 1
            FROM recommendation_history r
            WHERE r.paper_id = p.id
        )
        """
    query += """
        ORDER BY p.created_at DESC, p.year DESC, p.title ASC
    """
    rows = conn.execute(
        query,
        (min_year,),
    ).fetchall()
    candidates: list[Candidate] = []
    for row in rows:
        paper_id = row["id"]
        if paper_id in exclude_ids:
            continue
        created_at = parse_timestamp(row["created_at"])
        new_today = bool(created_since and created_at and created_at >= created_since)
        candidates.append(
            Candidate(
                id=paper_id,
                title=row["title"] or "",
                authors=row["authors"] or "",
                year=row["year"],
                abstract=row["abstract"] or "",
                url=row["url"] or "",
                journal=row["journal"] or "",
                created_at=row["created_at"] or "",
                new_today=new_today,
                citations=row["citations"],
                top_author_hindex=row["top_author_hindex"],
            )
        )
    return candidates


def score_candidate(candidate: Candidate) -> Candidate:
    text = normalize_space(" ".join([candidate.title, candidate.abstract, candidate.journal, candidate.url])).lower()
    hits: list[str] = []
    flags: dict[str, bool] = {}

    for label, phrases, weight in KEYWORD_GROUPS:
        matched = any(phrase in text for phrase in phrases)
        flags[label] = matched
        if matched:
            hits.append(label)

    # Agent axis: how strongly does the paper engage with AI agents / LLMs?
    agent_raw = 0.0
    if flags.get("agentic"):    agent_raw += 2.5
    if flags.get("llm"):        agent_raw += 1.5
    if flags.get("science"):    agent_raw += 1.0
    if flags.get("planning"):   agent_raw += 1.0
    if flags.get("robotics"):   agent_raw += 0.5
    if flags.get("agent_arch"): agent_raw += 0.5
    # Science combo only adds when domain is also present
    if flags.get("agentic") and flags.get("science") and (flags.get("materials") or flags.get("compmats")):
        agent_raw += 1.0

    # Domain axis: how strongly is the paper in computational materials science?
    domain_raw = 0.0
    if flags.get("materials"):  domain_raw += 2.5
    if flags.get("compmats"):   domain_raw += 2.5
    if flags.get("materials") and flags.get("compmats"):
        domain_raw += 1.0
    if "materials science" in text or "computational materials science" in text:
        domain_raw += 1.5

    # Penalties on both axes
    if any(term in text for term in NEGATIVE_TERMS):
        agent_raw = max(0.0, agent_raw - 3.0)
        domain_raw = max(0.0, domain_raw - 3.0)
    if "survey" in text or "review" in text:
        agent_raw = max(0.0, agent_raw - 0.5)

    # Recency bonus on domain axis
    if candidate.year:
        if candidate.year >= 2026:   domain_raw += 0.8
        elif candidate.year >= 2025: domain_raw += 0.5
        elif candidate.year >= 2024: domain_raw += 0.2

    # Normalize each axis to 0–1
    _AGENT_MAX = 7.5   # agentic+llm+science+planning+robotics+arch+combo
    _DOMAIN_MAX = 8.3  # materials+compmats+both_combo+matscience+year
    a = min(agent_raw / _AGENT_MAX, 1.0)
    d = min(domain_raw / _DOMAIN_MAX, 1.0)

    # Geometric mean × 10: both axes must be strong for a high score;
    # zero on either axis collapses the score to zero.
    final_score = max(0, min(10, int(round(10.0 * (a * d) ** 0.5))))

    track = "A" if any(flags.get(k) for k in ("agentic", "llm", "science", "materials", "compmats", "planning", "robotics")) else "unclear"

    candidate.score = final_score
    candidate.track = track
    candidate.keyword_hits = hits
    return candidate


def normalize_priority(candidate: Candidate) -> float:
    """Return the full priority score (base + bonuses) rescaled to 0–10."""
    raw = priority_key(candidate)[0]
    return round(raw * 10.0 / PRIORITY_SCORE_MAX, 2)


def priority_key(candidate: Candidate) -> tuple[float, int, int, str]:
    bonus = 0.0
    text = f"{candidate.title} {candidate.abstract}".lower()
    title_lower = candidate.title.lower()

    _strong_agent = any(t in text for t in ("agent", "agentic", "multi-agent", "tool use", "tool-use", "self-driving"))
    _llm_present = "llm" in text or "large language model" in text
    _llm_action = any(t in text for t in ("agent", "tool", "workflow", "autonomous", "agentic", "orchestrat"))
    is_agentic = _strong_agent or (_llm_present and _llm_action)
    title_agentic = any(t in title_lower for t in ("agent", "agentic", "multi-agent", "llm", "self-driving"))
    has_dft = "dft" in text or "density functional" in text
    title_dft = "dft" in title_lower or "density functional" in title_lower
    has_atomistic = "atomistic" in text
    title_atomistic = "atomistic" in title_lower
    has_materials = "materials" in text or "material" in text

    # Tier 1: DFT or atomistic in the *title* + agent anywhere — direct on-target papers
    if title_dft and is_agentic:
        bonus += 3.0
    elif title_atomistic and is_agentic:
        bonus += 2.5
    # Tier 2: DFT/atomistic only in abstract + agent
    elif has_dft and is_agentic:
        bonus += 1.5
    elif has_atomistic and is_agentic:
        bonus += 1.2
    elif has_dft:
        bonus += 0.5

    # Extra credit for agent/autonomous appearing in the title itself
    if title_agentic:
        bonus += 0.5

    if has_materials and is_agentic:
        bonus += 0.3
    if "robot" in text or "laboratory" in text:
        bonus += 0.3
    if candidate.new_today:
        bonus += 0.3
    if "survey" in text or "review" in text:
        bonus -= 0.5

    # Domain specificity: reward on-target computational materials papers,
    # penalize agentic papers with no connection to our domain.
    has_compmats_signal = (
        has_dft or has_atomistic or has_materials or
        "electronic structure" in text or
        "ab initio" in text or "ab-initio" in text or
        "force field" in text or "forcefield" in text or
        "vasp" in text or "quantum espresso" in text or
        "phonon" in text or "band structure" in text or
        "computational chemistry" in text or
        "molecular simulation" in text or
        "molecular dynamics" in text
    )
    has_strong_compmats = (
        "electronic structure" in text or
        "ab initio" in text or "ab-initio" in text or
        "force field" in text or "forcefield" in text or
        "vasp" in text or "quantum espresso" in text or
        "phonon" in text or "band structure" in text or
        "molecular dynamics" in text or
        "molecular simulation" in text
    )
    # Off-domain agentic penalty: agentic but zero computational materials signal
    if is_agentic and not has_compmats_signal:
        bonus -= 3.0
    # On-target boost: agentic + explicit computational methods signal
    if is_agentic and has_strong_compmats:
        bonus += 1.0

    # Journal / venue prestige
    venue = f"{candidate.journal or ''} {candidate.url}".lower()
    if any(s in venue for s in ("nature.com", "nature materials", "nature chemistry",
                                 "nature computational", "npj computational", "npj comput")):
        bonus += 1.5
    elif any(s in venue for s in ("science.org", "sciencemag", "science advances",
                                   "physical review letters", "journals.aps.org/prl",
                                   "pubs.acs.org", "jacs", "acs nano", "chemrxiv")):
        bonus += 1.0
    elif any(s in venue for s in ("neurips", "icml", "iclr", "cvpr", "aaai",
                                   "openreview.net")):
        bonus += 0.8

    # Citation count (rewards established, well-cited work)
    if candidate.citations is not None:
        if candidate.citations >= 500:
            bonus += 1.5
        elif candidate.citations >= 100:
            bonus += 0.8
        elif candidate.citations >= 30:
            bonus += 0.3

    # Senior author h-index (last 3 authors = typically PIs / group leaders)
    if candidate.top_author_hindex is not None:
        if candidate.top_author_hindex >= 80:
            bonus += 1.5
        elif candidate.top_author_hindex >= 50:
            bonus += 1.0
        elif candidate.top_author_hindex >= 30:
            bonus += 0.5

    return (candidate.score + bonus, candidate.year or 0, 1 if candidate.new_today else 0, candidate.title.lower())


def build_status_line(
    report_candidates: list[Candidate],
    fresh_candidates: list[Candidate],
    unseen_backfill_count: int,
    repeat_backfill_count: int,
) -> str:
    compmats_hits = sum(
        1
        for candidate in fresh_candidates
        if candidate.normalized_priority >= PRIMARY_THRESHOLD and (
            "materials" in candidate.title.lower() or "dft" in candidate.title.lower()
            or "computational materials" in f"{candidate.title} {candidate.abstract}".lower()
        )
    )
    lane_text = (
        "Computational-materials-agents lane returned relevant candidates."
        if compmats_hits
        else "Computational-materials-agents lane looked weak today."
    )
    n = len(report_candidates)
    if not report_candidates:
        return f"{lane_text} No papers cleared the threshold today, even after checking existing DB backfill."
    if repeat_backfill_count and unseen_backfill_count:
        return (
            f"{lane_text} Fresh hits were thin, so {unseen_backfill_count} existing-DB backfill papers and "
            f"{repeat_backfill_count} previously recommended DB papers were used. {n} papers in report."
        )
    if repeat_backfill_count:
        return (
            f"{lane_text} Fresh hits were exhausted, so {repeat_backfill_count} previously recommended DB papers were reused "
            f"to keep the report populated. {n} papers in report."
        )
    if unseen_backfill_count:
        return (
            f"{lane_text} Fresh hits were thin, so #{n - unseen_backfill_count + 1}-{n} are "
            f"existing-DB backfill from 2024+ papers not seen today. {n} papers in report."
        )
    return f"{lane_text} {n} papers in report. No backfill needed."


def trim_text(text: str, max_chars: int) -> str:
    text = normalize_space(text)
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


def fetch_html(url: str, timeout_sec: int) -> str | None:
    if not url:
        return None
    try:
        response = requests.get(url, headers=REQUEST_HEADERS, timeout=timeout_sec)
        response.raise_for_status()
        return response.text
    except Exception:
        return None


def arxiv_html_url(url: str) -> str | None:
    if "arxiv.org/abs/" in url:
        return url.replace("/abs/", "/html/")
    if "arxiv.org/html/" in url:
        return url
    return None


def extract_meta_content(soup: BeautifulSoup, *names: str) -> str:
    for name in names:
        meta = soup.find("meta", attrs={"name": name}) or soup.find("meta", attrs={"property": name})
        if meta and meta.get("content"):
            return normalize_space(meta["content"])
    return ""


def collect_heading_text(heading) -> str:
    if heading.parent and getattr(heading.parent, "name", None) == "section":
        text = normalize_space(heading.parent.get_text(" ", strip=True))
        head = normalize_space(heading.get_text(" ", strip=True))
        if text.startswith(head):
            text = text[len(head):].strip(" :.-")
        return text

    chunks: list[str] = []
    for sibling in heading.next_siblings:
        name = getattr(sibling, "name", None)
        if name and re.fullmatch(r"h[1-6]", str(name), flags=0):
            break
        if hasattr(sibling, "get_text"):
            chunks.append(sibling.get_text(" ", strip=True))
        else:
            chunks.append(str(sibling))
    return normalize_space(" ".join(chunks))


def extract_section_by_heading(soup: BeautifulSoup, pattern: re.Pattern[str]) -> str:
    for heading in soup.find_all(re.compile(r"^h[1-6]$")):
        text = normalize_space(heading.get_text(" ", strip=True))
        if pattern.search(text):
            return collect_heading_text(heading)
    return ""


def extract_abstract_and_conclusion(candidate: Candidate, timeout_sec: int = 15) -> tuple[str, str, list[str]]:
    notes: list[str] = []
    abstract = normalize_space(candidate.abstract)
    conclusion = ""

    urls_to_try: list[str] = []
    if candidate.url:
        arxiv_html = arxiv_html_url(candidate.url)
        if arxiv_html:
            urls_to_try.append(arxiv_html)
        urls_to_try.append(candidate.url)

    for url in urls_to_try:
        html = fetch_html(url, timeout_sec=timeout_sec)
        if not html:
            notes.append(f"fetch failed: {url}")
            continue
        soup = BeautifulSoup(html, "lxml")
        if not abstract or len(abstract) < 200:
            abstract = extract_meta_content(soup, "citation_abstract", "description", "og:description")
            if not abstract:
                abstract = extract_section_by_heading(soup, HEADING_PATTERNS["abstract"])
        if not conclusion:
            conclusion = extract_section_by_heading(soup, HEADING_PATTERNS["conclusion"])
        if abstract and conclusion:
            break

    return trim_text(abstract, 2400), trim_text(conclusion, 2400), notes


def select_takeaway(text: str) -> str:
    def looks_like_complete_sentence(sentence: str) -> bool:
        stripped = sentence.strip(" -•,;:\t")
        if len(stripped) < 30:
            return False
        if not stripped:
            return False
        if stripped[0].islower():
            return False
        if stripped.lower().startswith(("and ", "or ", "but ", "while ", "by ", "for ", "with ")):
            return False
        return True

    for sentence in sentence_split(text):
        lower = sentence.lower()
        if not looks_like_complete_sentence(sentence):
            continue
        if any(hint in lower for hint in TAKEAWAY_HINTS):
            return sentence
    sentences = sentence_split(text)
    for sentence in sentences:
        if looks_like_complete_sentence(sentence):
            return sentence
    return "Conclusion unavailable; abstract suggests it is worth a closer read."


def build_why_read(candidate: Candidate) -> str:
    text = f"{candidate.title} {candidate.abstract}".lower()
    if any(term in text for term in ("robot", "robotic", "laboratory", "synthesis")) and "materials" in text:
        return "Strongest closed-loop materials paper in the batch. It combines multi-agent reasoning with tools or robotics for end-to-end discovery rather than just chat-over-search. Best lab-autonomy read today."
    if ("dft" in text or "density functional theory" in text) and any(
        term in text for term in ("agent", "workflow", "automation", "autonomous", "materials discovery", "simulation")
    ):
        return "Best direct agentic DFT/workflow hit in the batch. It is about executing and stabilizing real computational workflows, not just proposing ideas. Core read if you care about automated DFT pipelines."
    if "dft" in text or "density functional theory" in text:
        return "Best computational-materials methods paper in the batch. It sharpens the electronic-structure lane directly, even without the agent layer. Worth reading if you care about better physics inputs for downstream automation."
    if "planning" in text or "workflow" in text or "orchestration" in text:
        return "Best architecture paper in today’s set. It focuses on planning and workflow structure, which usually matters more than prompt tricks for reliable scientific agents. Useful if you care about robust autonomy."
    if "survey" in text:
        return "Best overview paper in this batch. It helps map the space fast and should sharpen which primary papers deserve deeper reading next."
    return "High-signal paper for the current Track A/B priorities. It looks materially closer to usable scientific automation than generic AI-for-science filler."


def enrich_candidates(
    candidates: list[Candidate],
    *,
    deep_dive_limit: int,
    deep_dive_budget_sec: int,
    conn=None,
) -> None:
    deadline = time.monotonic() + deep_dive_budget_sec
    shortlist = sorted(candidates, key=priority_key, reverse=True)[:deep_dive_limit]
    for candidate in shortlist:
        if time.monotonic() >= deadline:
            candidate.notes.append("deep-dive budget exhausted before fetch")
            continue
        abstract, conclusion, notes = extract_abstract_and_conclusion(candidate)
        if abstract:
            candidate.abstract_excerpt = abstract
        if conclusion:
            candidate.conclusion_excerpt = conclusion
        candidate.notes.extend(notes)
        source_text = conclusion or abstract or candidate.abstract or candidate.title
        candidate.takeaway = select_takeaway(source_text)
        candidate.why_read = build_why_read(candidate)

        # Fetch Semantic Scholar metrics only when not already cached in DB
        if candidate.citations is None and candidate.top_author_hindex is None:
            if time.monotonic() < deadline:
                try:
                    metrics = fetch_paper_metrics(candidate.id, candidate.title)
                    candidate.citations = metrics["citations"]
                    if metrics["s2_authors"]:
                        candidate.top_author_hindex = fetch_top_hindex(metrics["s2_authors"])
                    if conn is not None:
                        update_paper_metrics(
                            conn,
                            candidate.id,
                            citations=candidate.citations,
                            top_author_hindex=candidate.top_author_hindex,
                        )
                except Exception as exc:
                    candidate.notes.append(f"s2 fetch failed: {exc}")

    for candidate in candidates:
        if not candidate.why_read:
            candidate.why_read = build_why_read(candidate)
        if not candidate.takeaway:
            source_text = candidate.abstract_excerpt or candidate.abstract or candidate.title
            candidate.takeaway = select_takeaway(source_text)


def render_report(
    *,
    report_candidates: list[Candidate],
    top_three: list[Candidate],
    status_line: str,
    unseen_backfill_count: int,
    repeat_backfill_count: int,
    fresh_passing_count: int,
) -> str:
    lines: list[str] = [status_line, ""]
    if not report_candidates:
        lines.append("No recommendation list today. Live search completed, but nothing in the fresh or existing 2024+ DB cleared the relevance threshold.")
        lines.append("")
        lines.append("Top 10 worth knowing")
        lines.append("")
        lines.append("None today.")
        lines.append("")
        lines.append("Top 3 worth reading today")
        lines.append("")
        lines.append("None today.")
        lines.append("")
        return "\n".join(lines).strip() + "\n"

    if repeat_backfill_count:
        lines.append(
            f"Only {fresh_passing_count} new papers passed the threshold, so existing DB backfill was used, including {repeat_backfill_count} previously recommended papers."
        )
        lines.append("")
    elif unseen_backfill_count:
        lines.append(f"Only {fresh_passing_count} new papers passed the threshold, so existing DB backfill was used.")
        lines.append("")
    elif len(report_candidates) < 10:
        lines.append(f"Only {len(report_candidates)} unseen papers passed the threshold today, so the list is shorter.")
        lines.append("")

    lines.append("Top 10 worth knowing")
    lines.append("")
    for i, candidate in enumerate(report_candidates, 1):
        if candidate.repeat_recommendation:
            suffix = " [repeat DB fallback]"
        elif not candidate.new_today:
            suffix = " [existing DB backfill]"
        else:
            suffix = ""
        lines.append(f"{i}. {candidate.title} — {candidate.url}{suffix}")

    lines.append("")
    lines.append("Top 3 worth reading today")
    lines.append("")
    for i, candidate in enumerate(top_three, 1):
        authors = candidate.authors or "Authors unavailable"
        lines.append(f"{i}) Title: {candidate.title}")
        lines.append("")
        lines.append(f"Authors/Link: {authors} — {candidate.url}")
        lines.append("")
        lines.append(f"Why you must read this today: {candidate.why_read}")
        lines.append("")
        lines.append("Key Takeaway")
        lines.append(f"- {candidate.takeaway}")
        lines.append("")

    return "\n".join(lines).strip() + "\n"


def _slack_oneliner(candidate: Candidate, max_chars: int = 120) -> str:
    source = candidate.abstract_excerpt or candidate.abstract or ""
    source = re.sub(r"&\w+;", " ", source)  # strip HTML entities
    source = re.sub(r"\s+", " ", source).strip()
    for sentence in sentence_split(source):
        s = sentence.strip()
        if len(s) > 40 and s[0].isalpha():
            return trim_text(s, max_chars)
    return trim_text(re.sub(r"&\w+;", " ", candidate.takeaway), max_chars)


def render_slack_report(
    *,
    report_candidates: list[Candidate],
    top_three: list[Candidate],
    papers_scanned: int,
    run_date: str,
) -> str:
    lines: list[str] = []

    lines.append(f":books: *Daily Paper Digest — {run_date}*")
    lines.append(f"{papers_scanned} papers evaluated across arXiv and Google Scholar")

    if not report_candidates:
        lines += ["", "---", "", "Nothing cleared the relevance threshold today."]
        return "\n".join(lines)

    lines += ["", "---", "", ":trophy: *Top 10 Papers Worth Knowing*", ""]
    for i, c in enumerate(report_candidates, 1):
        desc = _slack_oneliner(c)
        track_tag = f"(Track {c.track})" if c.track and c.track != "unclear" else ""
        suffix = ""
        if c.repeat_recommendation:
            suffix = " _(repeat)_"
        elif not c.new_today:
            suffix = " _(DB backfill)_"
        lines.append(f"{i}. *<{c.url}|{c.title}>* — {desc} {track_tag}{suffix}".rstrip())

    lines += ["", "---", "", ":fire: *Top 3 Must-Read Today*", ""]
    for i, c in enumerate(top_three, 1):
        authors = c.authors or "Authors unavailable"
        lines.append(f"*{i}. {c.title}*")
        lines.append(f"Authors/Link: {authors} — {c.url}")
        lines.append(f"Why you must read this today: {c.why_read}")
        lines.append(f"Key Takeaway: • {c.takeaway}")
        lines.append("")

    lines += ["---", "Track A: Agentic AI & self-driving labs · LLM tool-use for science · Agentic DFT & materials discovery"]
    return "\n".join(lines)


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def append_feedback_report(path: Path, items: list[dict]) -> None:
    """Append a batch of feedback items to the cumulative feedback_report.json."""
    if path.exists():
        try:
            report = json.loads(path.read_text())
        except Exception:
            report = {"batches": []}
    else:
        report = {"batches": []}
    report["batches"].append({"collected_at": utc_now_iso(), "items": items})
    path.write_text(json.dumps(report, indent=2) + "\n")


def bootstrap_recommendation_history_from_latest_payload(conn, payload_path: Path) -> bool:
    """Seed recommendation history from the latest saved payload if history is still empty."""
    if recommendation_history_count(conn) > 0 or not payload_path.exists():
        return False

    try:
        payload = json.loads(payload_path.read_text())
    except Exception:
        return False

    report_ids = payload.get("report_ids") or [
        candidate.get("id")
        for candidate in payload.get("report_candidates", [])
        if isinstance(candidate, dict) and candidate.get("id")
    ]
    report_ids = [paper_id for paper_id in report_ids if paper_id]
    if not report_ids:
        return False

    ran_at = payload.get("ran_at") or utc_now_iso()
    run_id = payload.get("run_id") or f"bootstrap-{re.sub(r'[^0-9A-Za-z]+', '-', ran_at).strip('-')}"
    report_candidates = payload.get("report_candidates", [])
    candidate_by_id = {
        candidate.get("id"): candidate
        for candidate in report_candidates
        if isinstance(candidate, dict) and candidate.get("id")
    }

    rows = conn.execute(
        f"SELECT id FROM papers WHERE id IN ({','.join('?' for _ in report_ids)})",
        report_ids,
    ).fetchall()
    present_ids = {row["id"] for row in rows}
    papers_to_record = [candidate_by_id.get(paper_id, {"id": paper_id}) for paper_id in report_ids if paper_id in present_ids]
    if not papers_to_record:
        return False

    record_recommendation_run(
        conn,
        run_id=run_id,
        started_at=ran_at,
        completed_at=ran_at,
        fresh_since=payload.get("fresh_since"),
        min_year=int(payload.get("min_year") or 2024),
        report_count=len(papers_to_record),
        top_count=int(payload.get("top_count") or min(3, len(papers_to_record))),
        search_minutes=float(payload.get("search_minutes") or 0.0),
        skip_search=bool(payload.get("skip_search")),
        papers=papers_to_record,
    )
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the daily Paper Scout recommendation workflow.")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="Path to SQLite database")
    parser.add_argument("--min-year", type=int, default=2024, help="Minimum publication year to persist/use")
    parser.add_argument("--num-results", type=int, default=400, help="Results per provider per query")
    parser.add_argument("--search-minutes", type=float, default=9.0, help="Hard budget for search phase")
    parser.add_argument("--deep-dive-limit", type=int, default=15, help="How many papers to enrich in phase 2")
    parser.add_argument("--deep-dive-budget-sec", type=int, default=240, help="Hard budget for abstract/conclusion fetching")
    parser.add_argument("--report-count", type=int, default=10, help="How many papers to show in the final report")
    parser.add_argument("--top-count", type=int, default=3, help="How many must-read papers to show")
    parser.add_argument("--analysis-dir", default=str(DEFAULT_ANALYSIS_DIR), help="Directory for debug artifacts")
    parser.add_argument("--report-out", default=None, help="Optional path to save the rendered report")
    parser.add_argument("--skip-search", action="store_true", help="Skip live search and build the report from the current DB")
    parser.add_argument("--fresh-since", default=None, help="Treat papers created at/after this ISO timestamp as fresh")
    parser.add_argument("--post-slack", action="store_true", help="Post the rendered report to Slack (requires SLACK_BOT_TOKEN and SLACK_CHANNEL in .env)")
    args = parser.parse_args()

    analysis_dir = Path(args.analysis_dir)
    analysis_dir.mkdir(parents=True, exist_ok=True)

    conn = get_connection(args.db)
    run_started_at = utc_now()
    run_id = f"run-{run_started_at.strftime('%Y%m%dT%H%M%S%fZ')}"
    history_bootstrapped = bootstrap_recommendation_history_from_latest_payload(
        conn,
        analysis_dir / "latest_recommendation.json",
    )
    # Sync Slack channel history so papers already shown are excluded from ranking
    try:
        n_synced = sync_posted_papers(conn)
        if n_synced:
            sys.stderr.write(f"Marked {n_synced} previously-posted papers in DB.\n")
    except Exception as exc:
        sys.stderr.write(f"Slack sync warning (non-fatal): {exc}\n")

    # Collect 👍/👎 reactions from previous run's paper messages
    try:
        feedback_items = collect_feedback(conn)
        if feedback_items:
            sys.stderr.write(f"Collected feedback for {len(feedback_items)} papers.\n")
            append_feedback_report(analysis_dir / "feedback_report.json", feedback_items)
    except Exception as exc:
        sys.stderr.write(f"Feedback collection warning (non-fatal): {exc}\n")
    explicit_fresh_since = parse_timestamp(args.fresh_since)
    last_recommendation_at = parse_timestamp(get_last_recommendation_at(conn))
    fresh_since = explicit_fresh_since or last_recommendation_at or run_started_at
    search_events: list[SearchEvent] = []
    early_stop = False

    try:
        if not args.skip_search:
            deadline = time.monotonic() + args.search_minutes * 60.0
            for item in QUERY_FAMILIES:
                if time.monotonic() >= deadline:
                    early_stop = True
                    break
                for provider in item.get("providers", ["arxiv", "scholar"]):
                    if time.monotonic() >= deadline:
                        early_stop = True
                        break
                    t0 = time.monotonic()
                    error = None
                    considered = 0
                    added = 0
                    try:
                        considered, added = run_provider_query(
                            conn=conn,
                            query=item["query"],
                            provider=provider,
                            num_results=args.num_results,
                            min_year=args.min_year,
                            sort_by=item.get("sort_by", "relevance"),
                        )
                    except Exception as exc:
                        error = str(exc)
                    elapsed = time.monotonic() - t0
                    search_events.append(
                        SearchEvent(
                            query=item["query"],
                            track=item["track"],
                            provider=provider,
                            considered=considered,
                            added=added,
                            elapsed_sec=round(elapsed, 3),
                            error=error,
                        )
                    )

        def _scored(candidates):
            result = []
            for c in candidates:
                c = score_candidate(c)
                c.normalized_priority = normalize_priority(c)
                result.append(c)
            return result

        unseen_candidates = _scored(fetch_candidates(
            conn,
            min_year=args.min_year,
            created_since=fresh_since,
            exclude_recommended=True,
        ))
        fresh_candidates = [c for c in unseen_candidates if c.new_today]
        existing_candidates = [c for c in unseen_candidates if not c.new_today]

        fresh_ranked = sorted(fresh_candidates, key=priority_key, reverse=True)
        existing_ranked = sorted(existing_candidates, key=priority_key, reverse=True)

        # Primary tier: normalized priority >= PRIMARY_THRESHOLD (8.0)
        fresh_passing = [c for c in fresh_ranked if c.normalized_priority >= PRIMARY_THRESHOLD]
        backfill_primary = [c for c in existing_ranked if c.normalized_priority >= PRIMARY_THRESHOLD]
        # Fallback tier: >= FALLBACK_THRESHOLD (7.0) but below primary
        backfill_fallback = [c for c in existing_ranked if FALLBACK_THRESHOLD <= c.normalized_priority < PRIMARY_THRESHOLD]

        report_candidates = fresh_passing[: args.report_count]
        need = max(0, args.report_count - len(report_candidates))
        report_candidates += backfill_primary[:need]
        need = max(0, args.report_count - len(report_candidates))
        report_candidates += backfill_fallback[:need]

        unseen_backfill_ranked = backfill_primary + backfill_fallback

        repeat_ranked: list[Candidate] = []
        if len(report_candidates) < args.report_count:
            selected_ids = {candidate.id for candidate in report_candidates}
            repeat_ranked = [
                candidate
                for candidate in sorted(
                    _scored(fetch_candidates(
                        conn,
                        min_year=args.min_year,
                        created_since=fresh_since,
                        exclude_ids=selected_ids,
                        exclude_recommended=False,
                    )),
                    key=priority_key,
                    reverse=True,
                )
                if candidate.normalized_priority >= FALLBACK_THRESHOLD
            ]
            for candidate in repeat_ranked:
                candidate.repeat_recommendation = True
            report_candidates += repeat_ranked[: max(0, args.report_count - len(report_candidates))]

        report_candidates = report_candidates[: args.report_count]
        unseen_backfill_count = sum(1 for candidate in report_candidates if not candidate.new_today and not candidate.repeat_recommendation)
        repeat_backfill_count = sum(1 for candidate in report_candidates if candidate.repeat_recommendation)

        deep_dive_pool: list[Candidate] = []
        seen_ids: set[str] = set()
        for candidate in fresh_ranked + unseen_backfill_ranked + repeat_ranked:
            if candidate.id in seen_ids:
                continue
            seen_ids.add(candidate.id)
            deep_dive_pool.append(candidate)
            if len(deep_dive_pool) >= max(args.deep_dive_limit, args.report_count):
                break

        enrich_candidates(
            deep_dive_pool,
            deep_dive_limit=args.deep_dive_limit,
            deep_dive_budget_sec=args.deep_dive_budget_sec,
            conn=conn,
        )

        enriched_map = {candidate.id: candidate for candidate in deep_dive_pool}
        report_candidates = [enriched_map.get(candidate.id, candidate) for candidate in report_candidates]
        top_three = sorted(report_candidates, key=priority_key, reverse=True)[: args.top_count]
        status_line = build_status_line(report_candidates, fresh_candidates, unseen_backfill_count, repeat_backfill_count)
        report = render_report(
            report_candidates=report_candidates,
            top_three=top_three,
            status_line=status_line,
            unseen_backfill_count=unseen_backfill_count,
            repeat_backfill_count=repeat_backfill_count,
            fresh_passing_count=len(fresh_passing),
        )

        payload = {
            "run_id": run_id,
            "ran_at": utc_now_iso(),
            "fresh_since": fresh_since.isoformat(),
            "history_bootstrapped": history_bootstrapped,
            "last_recommendation_at": last_recommendation_at.isoformat() if last_recommendation_at else None,
            "min_year": args.min_year,
            "skip_search": args.skip_search,
            "search_minutes": args.search_minutes,
            "early_search_stop": early_stop,
            "search_events": [asdict(event) for event in search_events],
            "fresh_candidate_count": len(fresh_candidates),
            "fresh_passing_count": len(fresh_passing),
            "backfill_count": unseen_backfill_count,
            "repeat_backfill_count": repeat_backfill_count,
            "unseen_candidate_count": len(unseen_candidates),
            "report_ids": [candidate.id for candidate in report_candidates],
            "top_three_ids": [candidate.id for candidate in top_three],
            "report_candidates": [asdict(candidate) for candidate in report_candidates],
        }
        write_json(analysis_dir / "latest_recommendation.json", payload)

        if args.report_out:
            report_path = Path(args.report_out)
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(report)

        record_recommendation_run(
            conn,
            run_id=run_id,
            started_at=run_started_at.isoformat(),
            completed_at=payload["ran_at"],
            fresh_since=fresh_since.isoformat(),
            min_year=args.min_year,
            report_count=len(report_candidates),
            top_count=len(top_three),
            search_minutes=args.search_minutes,
            skip_search=args.skip_search,
            papers=report_candidates,
        )

        sys.stdout.write(report)

        if args.post_slack:
            papers_scanned = sum(e.considered for e in search_events) if search_events else len(unseen_candidates)
            run_date = run_started_at.strftime("%B %-d, %Y")

            # Header
            post_message(
                f":books: *Daily Paper Digest — {run_date}*\n"
                f"{papers_scanned} papers evaluated · "
                f"React :thumbsup: = useful  :thumbsdown: = not relevant"
            )
            # Top-3 detailed analysis
            if top_three:
                lines: list[str] = [":fire: *Top 3 Must-Read Today*", ""]
                for i, c in enumerate(top_three, 1):
                    lines.append(f"*{i}. {c.title}*")
                    lines.append(f"Authors/Link: {c.authors or 'Authors unavailable'} — {c.url}")
                    lines.append(f"Why read: {c.why_read}")
                    lines.append(f"Takeaway: • {c.takeaway}")
                    lines.append("")
                lines += ["---", "Track A: Agentic AI & self-driving labs · LLM tool-use for science · Agentic DFT & materials discovery"]
                post_message("\n".join(lines))
            # Individual paper cards — one message per paper so reactions are trackable
            post_message(":trophy: *Top 10 — react :thumbsup: useful  :thumbsdown: not relevant:*")
            for i, c in enumerate(report_candidates, 1):
                desc = _slack_oneliner(c)
                suffix = " _(repeat)_" if c.repeat_recommendation else (" _(DB backfill)_" if not c.new_today else "")
                text = f"{i}. *<{c.url}|{c.title}>*\n> {desc}{suffix}"
                ts = post_message(text)
                save_paper_slack_ts(conn, c.id, run_id, ts)

            sys.stderr.write("Report posted to Slack.\n")
            mark_papers_posted(conn, [c.id for c in report_candidates])

        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
