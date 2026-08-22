# M4-FU02 — Post-S8 Coverage Audit and Human Review CSV Export

STATUS: `COMPLETE`

Change record: `CR-0019`.

## Scope

This independent follow-up performs two read-only operations:

1. audit only canonical roots whose first `SEARCH_CARD` observation is later
   than an explicit ISO-8601 cutoff;
2. export canonical roots and observed/excluded Thread nodes as UTF-8 BOM CSV
   for local human review.

It does not modify collection, detail enrichment, Structural Pattern analysis,
Generation-safe DTOs, or M5.

## Audit semantics

The cohort denominator is canonical roots first collected after the supplied
cutoff. Detail status, last failure, rounded Views availability/missing reason,
and clean Thread relationship evidence are counted only inside that cohort.
Missing rounded Views are classified separately as detail not run, page
timeout, rendered Views not present, extractor failure, or another observed
failure. Missing is never zero.

Clean Thread Sequence uses the latest detail observation with
`ROOT_DETAIL_PAGE` and optional `DOM_CONTIGUOUS_ROOT_AUTHOR_CHAIN` evidence.
Legacy/null relationship evidence is excluded and counted independently.

## Export contract

`sce-export-browser-posts` writes, by default:

- `data/exports/threads_posts.csv` — one canonical root per row;
- `data/exports/threads_thread_nodes.csv` — one root/node relationship result
  per row, with clean eligibility or an explicit exclusion reason.

`--since <timestamp>` isolates a cohort. Optional filters remain read-only.
The exporter opens SQLite in read-only mode, uses deterministic ordering,
preserves null separately from numeric zero, and writes `utf-8-sig` for common
Japanese spreadsheet applications. `data/exports/` is Git-ignored. Source text
and identity may appear only in these local `ANALYSIS_ONLY_SOURCE` exports.

The isolated live audit found all 130 post-S8 roots still `DETAIL_PENDING`.
Consequently this cohort currently has no rounded Views or Thread Sequence
evidence. The all-root and isolated CSV exports completed through a read-only
connection; aggregate verification is recorded in
`spec/evidence/M4_FU02_LIVE_VERIFICATION.json`.
