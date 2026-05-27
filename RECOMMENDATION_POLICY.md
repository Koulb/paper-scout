# Paper Scout Recommendation Policy

Use this file as the local mirror of the current paper-recommendation workflow.

Authority order:
1. Latest instructions from the *paper-club* chat
2. This file
3. Older README / skill guidance

## Goal

Use Paper Scout to find papers, parse them, and save them in the local SQLite database.

## Research Tracks

- **Track A:** Agentic LLM & AI for science
  - Autonomous lab agents
  - Self-driving labs
  - LLM tool-use for research
  - Closed-loop experiment design
  - AI scientists
  - Multimodal science models
  - AI agents in computational material science (e.g. agentic DFT/workflow automation, materials-discovery agents; queries should be broad enough to catch specific frameworks without depending on exact project names)

### Query Guidance

- Do not rely on exact-project-name queries alone.
- Include at least one broad query family for AI agents in computational material science.
- Include a broad density-functional-theory + LLM query lane (for example, `large language model density functional theory`) so XC-functional-discovery work is not missed.
- Keep an XC-functional-discovery lane (for example, `exchange-correlation functional discovery`) because this topic is easy to miss with generic agentic-DFT phrasing.
- If the computational-materials-agents lane returns weak or noisy candidates on a given run, broaden/refine queries within the search budget and note that briefly in the report.

## Daily Funnel

### Phase 1 — Initial Relevance Ranking

1. Time-box paper search to no more than 10 minutes.
2. Persist only papers from 2024 onward into the local SQLite database.
3. Review titles and keywords of all *new* papers.
4. Score each paper from 1-10 based strictly on relevance to the research tracks above.
5. Select exactly the Top 15 most relevant papers for deeper review when enough candidates exist.
6. In the user-facing report, show only papers that pass the relevance threshold of **7/10** or higher.
7. If fewer than 10 papers pass the threshold, report the smaller set and say so briefly.
8. If fresh 2024+ candidates are sparse, backfill from the best existing 2024+ papers already in the local DB that have *not* already been recommended, but still show only papers at **7/10** relevance or higher.

### Phase 2 — Deep Dive Analysis

For the Top 15 papers:

1. Read the abstract.
2. Read the conclusion when available.
3. Evaluate each paper on:
   - **Novelty** — new method or meaningful breakthrough?
   - **Impact** — likely to change how we approach active problems?
   - **Actionability** — open-source code or immediately useful ideas?

### Phase 3 — Read Today Selection

1. Choose the Top 3 papers that are most essential to read today.
2. Output:
   - **Top 10 worth knowing** — title + article link
   - **Top 3 worth reading today** with:
     - Title
     - Authors/Link
     - Why you must read this today (2-3 concise sentences)
     - Key Takeaway (one bullet from the conclusion)

## Scheduling

- Recommend papers every weekday at 10:00 America/New_York (Boston).
- Skip Saturday and Sunday.

## Style

- Default to Caveman Lite: terse, direct, technically exact.
- Expand only if the user explicitly asks for a clear explanation.
