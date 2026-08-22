# M4 Structural Pattern Intelligence Refresh

STATUS: `COMPLETE`

Change record: `CR-0018`.

The latest browser Source Store is audited after M4-FU01-S8 and the subsequent
human-selected collection/detail batch. Collection is paused for this refresh.
The refresh creates a reproducible root-only clean snapshot and replays the
deterministic M4 Structural Analyzer. It does not authorize M5.

## Dataset selection

- Canonical roots are identities with an observed `SEARCH_CARD` source.
- Every unassessed observation receives an append-only text-quality assessment.
- The newest bridged `VALID_TEXT` version per canonical root is selected.
- `INVALID_TEXT_DATE_METADATA`, `TEXT_UNAVAILABLE`, child-only identities, and
  ineligible legacy relationship evidence remain auditable but are excluded.
- Snapshot metadata records member count, quality exclusions, and selection
  contract/version.

## Analysis

The refresh produces independent First-Line, Post, and Thread Structural
Patterns. Thread Patterns use only the latest observed
`DOM_CONTIGUOUS_ROOT_AUTHOR_CHAIN`; they never use same-author identity alone.
Only repeated structures from two or more distinct roots are promoted.

Rounded detail-page Views remain separate approximate evidence with raw source
display retained in the Source Store, normalized approximate values,
`precision=ROUNDED`, and bands. They support descriptive distributions only;
missing is not zero, and exact ranking or causal inference is prohibited.

## Human review output

The aggregate report explains dataset quality, First-Line/Post/Thread
structures, support/confidence, previous-run changes, rounded Views coverage and
bands, limitations, and one readiness decision:

- `READY_FOR_M5`
- `READY_WITH_LIMITATIONS`
- `NOT_READY`

The decision is a quality assessment only, not authorization to start M5.
Generation-safe report data contains no source text, URL, author, or source ID.
Optional source examples may exist only in an ignored local
`ANALYSIS_ONLY_SOURCE` review artifact.

The version 2 root-only snapshot finalized with 236 valid members. The refreshed
report decision is `READY_WITH_LIMITATIONS`; this is not M5 authorization.
Aggregate verification is recorded in
`spec/evidence/M4_STRUCTURAL_REFRESH_VERIFICATION.json`.
