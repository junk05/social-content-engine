# M4-FU11 — Sequence Metadata Export Projection

STATUS: `COMPLETE`

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

## Completion evidence

The 2026-08-23 audit found two roots where a root `1 / 2` sequence had three
captured clean nodes. Both were over-capture, not missing children: the second
accepted child was outside the observed root total (one itself began `1 / 3`).
The extractor now caps an already branch-safe root-author chain at its observed
root total; it neither creates nodes nor relaxes author/branch checks. Both
audited roots reached two clean nodes after re-enrichment, and one was repeated
with extractor v15 to verify versioned provenance. The aggregate-only evidence
is `spec/evidence/M4_FU11_SEQUENCE_METADATA_VERIFICATION.json`.
