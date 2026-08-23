# M4-FU12 — Unified Views Observation History

STATUS: `COMPLETE`

Change record: `CR-0029`.

`DISPLAY_EXACT` and `ROUNDED` are two rendered representations of one
canonical Views metric. Every observation keeps raw display, normalized value,
precision, display format, observed time, extractor version, and provenance.
Historical observations remain append-only. Legacy rounded and display tables
are bridged into one immutable Views history and are never discarded.

Human Review exports project only the latest Views record as
`views_latest_raw`, `views_latest_value`, `views_latest_precision`, and
`views_latest_observed_at`; a separate history export supports audit. Exact and
rounded values must not be used for precision ranking against each other.

M5 remains out of scope.

## Completion evidence

Migration 28 bridges legacy exact and rounded tables into the immutable unified
Views history. New observations are dual-written into their legacy provenance
table and the unified history. Human Review now exposes latest Views columns
and `threads_views_history.csv`; both are local, read-only exports. Exact and
rounded observations retain their distinct precision and display formats.
