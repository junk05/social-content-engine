# M0 data model

The database starts with SQLite behind the `Repository` interface. Raw captures
are immutable evidence; normalized posts are replaceable derivations.

## Active M0 tables

- `collection_runs`: request, HTTP, timing, and collector provenance
- `raw_posts`: canonical item projection, item hash, source ID, and run linkage
- `normalized_posts`: queryable derived fields, unique by source and source ID
- `accounts`: observed author identity without invented attributes
- `thread_relationships`: observed reply/root relationships

## Reserved post-M0 tables

- `analysis_runs`, `post_analysis`, `pattern_instances`, `patterns`

Analyzer records must eventually include `analyzer_version`, `taxonomy_version`,
`model`, `prompt_version`, `analyzed_at`, and `source_post_id`.

## Design constraints

- The complete HTTP response body is retained byte-for-byte in `collection_runs`
  and ignored `data/raw/` files. Its SHA-256 is computed before parsing.
- `raw_posts` is an item-level projection produced after parsing. It is serialized
  deterministically for item comparison, but is not described as the original
  byte sequence.
- Recollecting the same `(source, source_post_id)` creates a new run-linked raw
  observation and upserts one normalized record.
- Missing API fields remain null/absent and are never inferred.
- `Silent Engagement` is a future hypothesis. Profile visits, follows, thread
  opens, and deep reads are not treated as observed unless an official API
  actually supplies them.
- The future action-first model is `Action -> Psychology -> Structure -> Content`;
  M0 stores evidence only and does not generate content.

## Additive M3 browser observations

Browser collection does not create API-style raw responses or place DOM content
in `collection_runs` / `raw_posts`. It uses a separate evidence boundary:

- `browser_post_identities`: one Threads identity per canonical normalized
  `https://www.threads.net/@username/post/code` URL; `source_post_id` is
  supplemental and nullable.
- `browser_observations`: immutable accepted search-card or post-detail capture
  envelopes. Recollection always creates another observation.
- `browser_observed_fields`: field-level value, surface, time, and extractor
  provenance linked to one immutable observation.
- `browser_metric_observation_statuses`: immutable per-counter availability
  evidence for detail observations. `OBSERVED` includes exact zero;
  `NOT_PRESENT`, `NOT_OBSERVED`, and `EXTRACTION_FAILED` remain distinct and
  never synthesize a counter value.
- `browser_normalized_versions`: immutable canonical projections. An identical
  payload hash reuses a version; a changed observed payload creates version
  `N+1`.

`browser_post_identities.status` records the latest workflow state:
`COLLECTED`, `DETAIL_PENDING`, `DETAIL_ENRICHED`, or `DETAIL_FAILED`. Search-card
observations without an observed `view_count` become `DETAIL_PENDING`. Status
updates never remove observation or failure history.

Browser evidence stores only the closed observation contract. Raw DOM, HTML,
cookies, authorization headers, access tokens, passwords, and hidden page state
are forbidden. A nullable `normalized_post_id` is reserved for the later M3
integration step; browser collection never invents an API `source_post_id`.
