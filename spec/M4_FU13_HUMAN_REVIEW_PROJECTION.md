# M4-FU13 — Human Review Projection Repair

STATUS: `IN_PROGRESS`

Change record: `CR-0030`.

Human Review source selection uses one deterministic rule for root and Thread
CSV rows. Observations explicitly assessed as `INVALID_TEXT_DATE_METADATA`,
`INVALID_TEXT_TOPIC_TAG_METADATA`, or `TEXT_UNAVAILABLE` are lower priority
than non-invalid evidence, including a newer unassessed observation. Within the
same eligibility tier, `POST_DETAIL` precedes `SEARCH_CARD`, then the newest
`collected_at` and observation id win. If only invalid evidence exists, the
newest evidence remains visible with its quality status for audit; it is not
represented as clean evidence.

An absent detail queue is projected as `NOT_QUEUED`, never
`DETAIL_PENDING`. Existing `EXCLUDED` remains the established local UI status
for an explicitly excluded queue item. Requeueing a human-selected legacy root
may create its missing durable queue from existing `SEARCH_CARD` provenance;
source observations remain append-only.

Text-quality assessment is intentionally produced by the clean dataset
analysis path, not browser ingestion. Therefore `UNASSESSED` is a valid Source
Store state and every Human Review projection must handle it explicitly.

The topic-tag extractor is unchanged. M5 remains out of scope.
