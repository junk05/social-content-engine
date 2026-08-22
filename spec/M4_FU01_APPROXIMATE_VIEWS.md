# M4-FU01-S7 — Approximate Detail-Page Views

STATUS: `APPROVED / IN_PROGRESS`

Contract version: `M4-FU01-APPROXIMATE-VIEWS-V1`

## Decision

A rounded Views display visible on a selected post's detail page is immutable
descriptive evidence, not an exact public counter. It is stored separately as
`approximate_views` with:

- `display`: the observed localized display token;
- `normalized_approx`: the deterministic magnitude normalization;
- `precision`: `ROUNDED`;
- `source`: `POST_DETAIL_PAGE`;
- `view_band`: `LT_1K`, `1K_10K`, `10K_100K`, `100K_1M`, or `1M_PLUS`;
- `observed_at`, `extractor_version`, and `normalizer_version`.

`public_counters.view_count` remains exact-only and nullable. Rounded displays
must never populate it. Missing approximate Views remain absent, never zero.
The original display token remains in the analysis-only Source observation so
normalization can be replayed after a future rule revision.

## Collection path

The selected-post detail page is sufficient for full visible text, approximate
Views, and observable Thread Sequence. Activity-sheet automation is optional
additional enrichment for exact Likes, Reposts, Quotes, or other rendered
metrics; it is not required for detail success or Views collection.

## Analysis boundary

Approximate Views may support descriptive comparisons, rough view bands, and
pattern-level distributions. It must not support exact ranking, small-difference
comparison, causal claims, or reconstruction of an unavailable exact value.
No numeric range is inferred until the platform's rounding convention is
observed and specified.

## Live verification

One already selected detail page with a rounded Views display must produce a
`DETAIL_ENRICHED` observation with exact `view_count=null`, a provenance-backed
`approximate_views` record, full visible text, and any observable Thread
Sequence. No Activity sheet action is required for this verification.
