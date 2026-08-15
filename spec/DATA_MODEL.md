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
