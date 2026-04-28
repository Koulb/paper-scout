# Paper Scout Recommendation Policy

Use this file as the local mirror of the current paper-recommendation workflow.

Authority order:
1. Latest instructions from the *paper-clib* chat
2. This file
3. Older README / skill guidance

## Goal

Use Paper Scout to find papers, parse them, and save them in the local SQLite database.

## Research Tracks

- **Track A (Priority):** Agentic LLM & AI for science
  - Autonomous lab agents
  - Self-driving labs
  - LLM tool-use for research
  - Closed-loop experiment design
  - AI scientists
  - Multimodal science models
- **Track B:** Beyond DFT electron-phonon coupling, machine learning of the Hamiltonian and phonons

## Daily Funnel

### Phase 1 — Initial Relevance Ranking

1. Review titles and keywords of all *new* papers.
2. Score each paper from 1-10 based strictly on relevance to the research tracks above.
3. Select exactly the Top 15 most relevant papers for deeper review when enough candidates exist.

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

- Recommend papers every weekday at 10:00 UTC.
- Skip Saturday and Sunday.

## Style

- Default to Caveman Lite: terse, direct, technically exact.
- Expand only if the user explicitly asks for a clear explanation.
