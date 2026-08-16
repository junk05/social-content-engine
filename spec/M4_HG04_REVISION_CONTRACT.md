# M4 HG-04 Revision Contract

STATUS: `APPROVED REVISION UNDER CR-0004`

This contract supplements `M4_VIRAL_PATTERN_INTELLIGENCE_V2.md`. M4 remains
`IN_PROGRESS`; M5 Content Generation remains out of scope.

## First-Line coverage audit

The report must expose aggregate-only funnel counts for the frozen review
snapshot: analyzed posts, first line available, feature detected, no meaningful
feature detected, pattern candidate, singleton candidate, support `>=2`,
promoted pattern, and excluded generic pattern. It must also report frequency
by rhetorical, psychological, and certainty feature dimensions. Source text,
URLs, usernames, and source identifiers are forbidden in this audit.

`ASSERTION + NONE + UNKNOWN` is a generic signature. It may be counted as an
excluded diagnostic, but must never be ranked as an actionable Pattern.

## Psychological hypotheses

For a supported abstract signature, the report may derive only closed,
explicitly labelled `PSYCHOLOGY_HYPOTHESIS` mappings:

- contrarian claim or expectation reversal -> `EXPECTATION_VIOLATION` ->
  `ATTENTION`, `CONTINUE_READING`;
- reader targeting or identity callout -> `SELF_RELEVANCE` ->
  `CONTINUE_READING`;
- curiosity gap or incomplete information -> `INFORMATION_GAP` ->
  `CONTINUE_READING`.

These are not causal performance claims and do not establish reader behavior.

## Metric audit and selection

Every browser-observed counter is audited separately from M4 snapshot selection.
Missing counters remain `NOT_OBSERVED_BY_BROWSER_COLLECTOR`, never zero. M4 may
select counter observations from the same browser identity only when they were
captured no later than the frozen snapshot finalization timestamp, preserving
the browser-observation ID, surface, extractor version, and observation time.

Metric-specific descriptive association is allowed only at sufficient observed
coverage and must remain non-causal. No parent-to-self-reply Pattern may be
created without an observed same-author sequence edge.
