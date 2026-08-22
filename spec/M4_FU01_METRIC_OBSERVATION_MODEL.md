# M4-FU01-S6 — Nullable Metric Observation Model

STATUS: `APPROVED / IN_PROGRESS`

Contract version: `M4-FU01-METRIC-OBSERVATION-V1`

## Decision

A valid visible `POST_DETAIL` observation enriches the selected post even when
one or more public metrics are absent. Detail success and metric availability
are independent. Each metric records exactly one of:

- `OBSERVED`: an exact nonnegative integer, including zero, was visible;
- `NOT_PRESENT`: the Activity sheet was visible but did not render that metric;
- `NOT_OBSERVED`: the relevant metric surface was not observed;
- `EXTRACTION_FAILED`: its label was visible but no exact integer could be read.

A non-null counter must be `OBSERVED`; a null counter must never be `OBSERVED`.
Rounded values are not converted to exact counts. Status evidence is immutable,
versioned, field-specific, and linked to the source observation.

## Live verification

The already diagnosed no-Views post must become `DETAIL_ENRICHED` with
`view_count=null` and `view_count=NOT_PRESENT`, while any exact visible
engagement metrics remain `OBSERVED`. A separate known post whose Activity
sheet visibly contains exact Views verifies exact extraction and ingestion.

Batch adoption additionally requires that one absent metric does not fail an
item and existing retry, resume, provenance, and failure isolation regressions
remain green. No inferred metric, new click method, batch live run, or M5 scope
is authorized by this contract.
