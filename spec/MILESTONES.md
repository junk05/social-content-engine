# Milestones

## M0 — Real Threads data capture

Status: `COMPLETE`

Definition of Done:

1. Threads API capability matrix is evidence-backed.
2. Authentication method is determined.
3. At least one real public post is obtained through an official permitted API.
4. The unmodified raw response is stored.
5. A normalized post is derived.
6. Provenance is stored.
7. Recollection does not create a duplicate normalized post.
8. A sanitized fixture exists.
9. Automated tests pass.
10. CI passes.

Items 1–10 are verified. The real API response was preserved locally, its sanitized fixture was committed, and GitHub Actions passed on Python 3.9 and 3.12. Evidence: `evidence/M0_LIVE_VERIFICATION.json`.

## M1 — Analyzer

Status: `COMPLETE`

Approved specification: `spec/M1_ANALYZER.md` (`M1-ANALYZER-V1`).

Goal: convert normalized public-post evidence into versioned, reviewable structured analysis while preserving the boundary between observation and inference.

Definition of Done:

1. Canonical Analyzer Input preprocessing and SHA-256 implemented.
2. M1 Analyzer Output schema/taxonomy implemented.
3. `analysis_runs` and `post_analysis` persistence implemented without overwriting historical analyses.
4. Analyzer adapter boundary and deterministic mock adapter implemented.
5. Evidence-span validation rejects unsupported/inconsistent output.
6. Analyzer orchestration, idempotency/replay, and minimal CLI implemented.
7. Golden Cases cover Japanese text, ambiguity, malformed output, and replay.
8. Existing M0 tests remain green.
9. CI passes on supported Python versions.
10. No credentials, live raw responses, or unsupported private inferences are committed.

M1 does not include content generation, automatic publishing, virality prediction, creator profiling, dashboards, or Fortune Engine integration.

Items 1–10 are verified. Local validation passed with 41 tests, and GitHub
Actions passed on Python 3.9 and 3.12. Evidence:
`evidence/M1_VERIFICATION.json`.

## M2 — Cross-post Pattern Mining & Dataset Expansion

Status: `IN_PROGRESS`

Approved specification: `spec/M2_PATTERN_MINING.md`
(`M2-PATTERN-MINING-V1`).

Goal: expand the permitted public Threads dataset, batch M1 analysis, and derive
reproducible multi-post structural Pattern candidates with evidence and
provenance. The initial target is 100 unique public posts across five or more
genres with both TOP and RECENT, bounded by a 200-post hard ceiling and measured
API constraints.

Definition of Done is authoritative in `spec/M2_PATTERN_MINING.md` section 14.

M2's API-wide public collection remains blocked by Meta approval requirements.
Evidence: `evidence/M2_DOD_AUDIT.json`. M3 does not rewrite this result.

## M3 — Threads Browser Collector & Detail Enricher

Status: `COMPLETE`

Approved specification: `spec/M3_BROWSER_COLLECTOR.md`
(`M3-BROWSER-COLLECTOR-V1`).

Goal: let a person select public Threads posts during ordinary browsing, ingest
only those visible observations through a localhost receiver, and explicitly
enrich saved detail pages without automated search or crawling.

Definition of Done is authoritative in `spec/M3_BROWSER_COLLECTOR.md` section 10.
Verification: `spec/evidence/M3_DOD_AUDIT.json`.

## M4 — Viral Pattern Intelligence

Status: `IN_PROGRESS`

Approved specifications: `spec/M4_VIRAL_PATTERN_INTELLIGENCE.md`,
`spec/M4_VIRAL_PATTERN_INTELLIGENCE_V2.md` (`CR-0003`), and
`spec/M4_STRUCTURAL_PATTERN_EXTRACTION.md` (`CR-0006`).

Goal: derive evidence-backed, reusable rhetorical Pattern Intelligence from
human-selected browser observations, without claiming causal performance or
implementing content generation.

The initial HG-04 report was rejected for revision. M4 now validates
genre-independent deterministic Structural Patterns before any optional LLM
enrichment and repeats HG-04 before any M5 Content Generation scope can begin.

## Deferred until later milestones

- content generation and automatic publishing
- Fortune Engine integration
- dashboards, production deployment, and large-scale infrastructure
