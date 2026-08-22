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

Status: `COMPLETE`

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

Status: `COMPLETE`

Approved specifications: `spec/M4_VIRAL_PATTERN_INTELLIGENCE.md`,
`spec/M4_VIRAL_PATTERN_INTELLIGENCE_V2.md` (`CR-0003`), and
`spec/M4_STRUCTURAL_PATTERN_EXTRACTION.md` (`CR-0006`).

Goal: derive evidence-backed, reusable rhetorical Pattern Intelligence from
human-selected browser observations, without claiming causal performance or
implementing content generation.

HG-04 approved the clean, genre-independent deterministic Structural Pattern
report. Old date-metadata text observations are retained for audit but excluded
from clean structural snapshots. Observed metric coverage remains insufficient
for performance-superiority or causal claims. Any M5 Content Generation scope
requires separate approval and its applicable Human Gate.

### M4-FU01 — Automated Detail Enrichment

Status: `COMPLETE`

Approved specification: `spec/M4_FU01_AUTOMATED_DETAIL_ENRICHMENT.md`
(`CR-0008`). This follow-up automates detail enrichment only after one explicit
user start and only for posts already selected through `Pattern収集`. It does
not reopen M4 quality approval and does not authorize M5.

HG-03 passed with a paced 50-item batch: 48 items enriched successfully, two
page timeouts were isolated, and all successful observations entered the clean
snapshot as valid text. Evidence: `spec/evidence/M4_FU01_LIVE_E2E.json`.

### M4-FU01-S1 — Debugger Input Live Spike

Status: `FAILED / RE-EVALUATION REQUIRED`

Approved specification: `spec/M4_FU01_DEBUGGER_INPUT_SPIKE.md` (`CR-0009`).
This material-permission spike is restricted to one selected post and one
dedicated tab. Its single HG-03 run returned `SHEET_NOT_OBSERVED`; further
debugger automation requires a separately approved re-evaluation. It does not
authorize M5.

### M4-FU01-S2 — Debugger Foreground Input Live Spike

Status: `FAILED / RE-EVALUATION REQUIRED`

Approved specification: `spec/M4_FU01_DEBUGGER_FOREGROUND_SPIKE.md`
(`CR-0010`). Its single HG-03 run returned
`SHEET_NOT_OBSERVED_FOREGROUND`; no further interaction expansion is
authorized. It does not authorize M5.

### M4-FU01-S3 — macOS Native Input Live Spike

Status: `FAILED / RE-EVALUATION REQUIRED`

Approved specification: `spec/M4_FU01_NATIVE_INPUT_SPIKE.md` (`CR-0011`).
Its single HG-03 run returned `NATIVE_INPUT_FAILED`; it does not authorize
batch automation or M5.

### M4-FU01-S4 — Native Coordinate Calibration

Status: `CLICK PATH VERIFIED / EXTRACTION FOLLOW-UP ACTIVE`

Approved specification: `spec/M4_FU01_NATIVE_COORDINATE_CALIBRATION.md`
(`CR-0012`). Stage 1 is move-only; the existing Quartz click remains gated on
human confirmation of exact cursor alignment. Alignment and native clicking
succeeded, but the repaired bounded probe did not capture the exact view count,
so batch adoption remains pending. The earlier non-adoption decision is
superseded by the approved read-only S5 follow-up. It does not authorize M5.

### M4-FU01-S5 — Activity Sheet DOM Diagnostic

Status: `ROOT_CAUSE_CONFIRMED / RE-EVALUATION REQUIRED`

Approved specification: `spec/M4_FU01_ACTIVITY_DOM_DIAGNOSTIC.md`
(`CR-0013`). It retains the calibrated Quartz click and adds only read-only
sheet diagnosis, exact view extraction, and one-post ingest verification. The
live sheet rendered engagement metrics but no Views field; missing Views remain
unavailable. Native input stays viable but is not yet adopted for batch use.

### M4-FU01-S6 — Nullable Metric Observation Model

Status: `COMPLETE`

Approved specification: `spec/M4_FU01_METRIC_OBSERVATION_MODEL.md`
(`CR-0014`). `DETAIL_ENRICHED` no longer requires Views. Per-metric observed,
absent, unobserved, and extraction-failure states remain independent and
provenance-backed. Exact Views capability still requires separate live proof.

### M4-FU01-S7 — Approximate Detail-Page Views

Status: `COMPLETE`

Approved specification: `spec/M4_FU01_APPROXIMATE_VIEWS.md` (`CR-0015`).
Rounded Views visible on the selected detail page are stored as a separate
descriptive signal and never as exact `view_count`. Activity-sheet enrichment
is optional; exact ranking, inferred Views, causal claims, and M5 remain out of
scope.

One selected-post Live E2E passed without opening Activity: the immutable
detail observation retained non-empty source text, exact `view_count=null`, and
separate rounded Views normalization/provenance. No live value, text, URL, or
author identity is committed. Evidence:
`spec/evidence/M4_FU01_S7_LIVE_VERIFICATION.json`.

A repaired paced 50-item batch completed 48 items with two isolated page
timeouts. All 48 enriched observations were valid clean source text; 42 retained
rounded Views evidence and none inferred unavailable exact Views. Legacy invalid
observations remain immutable audit evidence. Aggregate verification is in
`spec/evidence/M4_FU01_LIVE_E2E.json`.

### M4-FU01-S8 — Self-Reply Content Collection

Status: `COMPLETE`

Approved specification: `spec/M4_FU01_SELF_REPLY_COLLECTION.md` (`CR-0016`).
One selected root may append only visible same-author reply details and existing
Thread Sequence evidence. General reply crawling, inferred edges, generation,
and M5 remain out of scope.

The initial HG-03 result was rejected after human review found two root-author
replies below other-author branches. CR-0017 requires branch-aware traversal and
a repeat live result of exactly one root plus three eligible self replies.

The repeat HG-03 passed: extractor v6 stored one root plus three eligible
root-author continuation nodes and excluded both conversation-branch replies.
Historical v5 evidence remains immutable and ineligible for clean analysis.

### M4 Structural Pattern Intelligence Refresh

Status: `COMPLETE`

Approved specification: `spec/M4_STRUCTURAL_REFRESH.md` (`CR-0018`). The latest
root-only valid-text browser snapshot is being replayed through deterministic
First-Line, Post, and observed Thread Structure analysis with descriptive
rounded Views associations. The resulting readiness decision does not authorize
M5.

The clean snapshot contains 236 valid roots and excludes two legacy
date-metadata observations. The report decision is `READY_WITH_LIMITATIONS`
because rounded Views cover 79 roots (33.5%) and 60 First Lines retain no
specific component beyond the generic assertion form. M5 remains unauthorized.

### M4-FU02 — Post-S8 Coverage Audit and Human Review Export

Status: `COMPLETE`

Approved specification: `spec/M4_FU02_COVERAGE_AUDIT_EXPORT.md` (`CR-0019`).
This read-only follow-up audits the isolated post-S8 root cohort and exports
local analysis-only CSV files for human review. It does not reopen Structural
analysis or authorize M5.

The post-S8 audit isolated 130 roots and found all 130 still `DETAIL_PENDING`;
rounded Views and clean Thread evidence therefore have 0% coverage in that
cohort. Read-only all-root and post-S8 CSV exports were generated locally and
remain Git-ignored. M5 remains unauthorized.

### M4-FU03 — Post-S8 Thread Coverage Diagnostic

Status: `IN_PROGRESS`

Approved specification: `spec/M4_FU03_THREAD_COVERAGE_DIAGNOSTIC.md`
(`CR-0020`). Thread Structural Pattern refresh is paused while the isolated
post-S8 cohort is audited and one to three human-confirmed self-reply roots are
diagnosed with branch evidence intact. First-Line and Post results remain
unchanged. M5 remains unauthorized.

### M4-FU04 — Collected Post Management

Status: `COMPLETE`

Approved specification: `spec/M4_FU04_COLLECTED_POST_MANAGEMENT.md`
(`CR-0021`). This independent M4-FU01 follow-up adds a local Extension list of
collected roots plus audited exclude/re-enable/re-enrich controls. Source
evidence is never deleted, excluded identities cannot be batch-claimed, and M5
remains unauthorized.

The local collected-root list, status filters, audited exclusion, and explicit
re-enrich/re-enable actions are implemented. Excluded items are omitted from
pending lists, failed retries, and batch claims without deleting historical
evidence. M5 remains unauthorized.

### M4-FU05 — Extension Human Review CSV Downloads

Status: `COMPLETE`

Approved specification: `spec/M4_FU05_EXTENSION_CSV_EXPORT.md` (`CR-0022`).
The Extension options page downloads the existing canonical-root and Thread
Sequence Human Review CSVs through an exact-origin loopback endpoint. The
currently selected status filter is preserved, CSV rendering remains read-only
and UTF-8 BOM compatible, and no Generation-facing or M5 scope is introduced.

## Deferred until later milestones

- content generation and automatic publishing
- Fortune Engine integration
- dashboards, production deployment, and large-scale infrastructure
