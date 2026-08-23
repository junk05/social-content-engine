# M4-FU09 — Publication-Time Observation

STATUS: `IN_PROGRESS`

Change record: `CR-0026`.

## Purpose

Preserve the observed publication time separately from collection time, so later
M4 analysis can make descriptive timing comparisons without treating capture
time as publication time.

## Acquisition order

The Detail extractor first uses a visible semantic `time[datetime]` element in
the canonical post container. Its exact attribute value is retained as
`published_at_raw`; a valid explicit-offset ISO-8601 value becomes
`published_at`. `timezone_basis` records `TIME_DATETIME_EXPLICIT_OFFSET`.

Relative labels such as `2時間` remain UI metadata and never become a precise
publication timestamp. Hover is not implemented while the direct semantic
attribute is available. If it is absent or has no explicit timezone, all
publication fields remain null/`NOT_OBSERVED`; no timezone is inferred.

## Storage and provenance

Each post-detail observation stores:

- `published_at_raw`;
- `published_at` (normalized ISO-8601 with offset);
- `published_timezone_basis`;
- observation `collected_at` / `observed_at` and extractor version through the
  existing append-only envelope and observed-field provenance.

The legacy `timestamp` field remains a compatibility alias for the same direct
semantic timestamp. `collected_at` is never used as a fallback for
`published_at`.

Derived local date, time, weekday, and hour are computed from `published_at`
for read-only exports. They are not an independent source of truth. The
timezone in the timestamp itself is the local basis; absent timezone remains
unknown. `age_at_observation` remains derivable as `observed_at - published_at`.

## Human Review CSV

Canonical-root CSV gains `published_at`, `published_date`, `published_time`,
`published_weekday`, and retains the existing `collected_at`. Thread-node CSV
receives the same publication-time representation when its own detail source
contains it. CSV remains a local human-review artifact, not a Generation DTO.

## Boundaries

- No hover, mouse, keyboard, debugger, network, storage, or credential access
  is added for timing collection.
- Source timestamps stay analysis-only and are never exposed through
  Generation-safe patterns.
- Missing or malformed values remain explicit and are not converted to zero,
  current time, or a guessed timezone.
- M5 remains unauthorized.

## Definition of Done

1. exact `time[datetime]` values are preserved with raw/normalized/timezone
   semantics;
2. no relative-time text becomes an exact publication value;
3. source and normalized contracts preserve timing provenance;
4. root and eligible self-reply exports provide deterministic derived timing
   columns;
5. tests, validation, and CI pass; and
6. a bounded live read-only verification confirms the direct attribute path or
   explicitly records it unavailable.
