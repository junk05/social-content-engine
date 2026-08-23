# M4-FU11 — Sequence Metadata Export Projection

STATUS: `IN_PROGRESS`

Change record: `CR-0028`.

## Root cause

The extractor and receiver already retain DOM-confirmed sequence metadata. The
Human Review CSV selected one historical `POST_DETAIL` row for source text,
preferring `VALID_TEXT` before recency. That correct text-quality choice also
incorrectly supplied sequence columns, so pre-indicator observations hid the
latest indicator evidence.

## Contract

`source_text` keeps its existing quality-first analysis-only selection. The
three sequence columns instead project from the latest canonical root
`POST_DETAIL` observation independently. The export also exposes the expected
root `thread_total` beside the already clean, branch-safe `self_reply_count`,
allowing human comparison of expected and captured clean node counts without
creating or weakening relationship evidence.

The Human Review CSV presents a DOM raw fraction such as `1 / 2` as `1 of 2`
to avoid Excel date coercion. This is presentation only: the immutable source
payload retains `1 / 2`, while `thread_position`, `thread_total`, and
`clean_sequence_node_count` remain the canonical numeric review columns.

## Boundaries

- No collector, waiting, completeness, or branch-aware relationship logic is
  changed.
- Indicators remain UI metadata, not inferred edges.
- Existing source observations and provenance stay immutable.
- M5 remains out of scope.
