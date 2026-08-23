# M4-FU10 — Engagement Metric Observation Repair

STATUS: `IN_PROGRESS`

Change record: `CR-0027`.

## Purpose

Repair deterministic observation of public Like, Reply, Repost, and Quote
counts on an already-open, user-selected Threads detail page. This is separate
from detail-page Views observation and does not reopen Structural analysis.

## Audit first

Before changing extraction semantics, a read-only diagnostic runs on one to
three known canonical detail pages. It records only engagement-control
structure and display values: metric label, control tag/role/ARIA context,
bounded parent/sibling shape, raw numeric display, and exact-versus-rounded
shape. It never copies post text, URL, author identity, credentials, storage,
cookies, or network data into repository artifacts.

Generated CSS classes are not an extraction contract. A repaired extractor must
derive a metric only from its rendered engagement-control context, never from
numbers in the author body, topic tag, timestamp, sequence indicator, or other
page content.

## Observation semantics

Each metric keeps independent raw display, normalized value, precision,
observation status, observed time, extractor version, and provenance. Exact
integer displays use `DISPLAY_EXACT`; magnitude displays use `ROUNDED`.
`0`, `NOT_OBSERVED`, `NOT_PRESENT`, and `EXTRACTION_FAILED` are distinct.
Only values visibly observed on the control surface are stored.

### Bounded DOM audit result

Three canonical detail pages were audited read-only. Reply and Repost each
exposed a local `svg[role=img][aria-label]` with a local numeric display. Like
had no usable icon label, but the unlabelled numeric action immediately before
the semantically-labelled Reply action was consistent across all three pages.
That bounded action-order relationship is a versioned structural contract, not
a CSS-class selector. Quote and Share had no numeric detail-control display in
the audit; they remain `NOT_OBSERVED`, not zero. The source-text-free aggregate
record is `spec/evidence/M4_FU10_ENGAGEMENT_DOM_AUDIT.json`.

## Recovery

Existing observations remain immutable. Roots already detail-enriched but with
one or more currently observable (`Like`, `Reply`, `Repost`) engagement metrics
unobserved are selected by an explicit, non-destructive re-enrichment candidate
path. Quote and Share do not make a root a retry candidate until a numeric
detail-control form is actually observed. No all-root refresh is implied;
excluded roots remain excluded and existing queue/resume/failure isolation
semantics remain intact.

## Human Review CSV

The existing count columns remain the canonical human-review values. Source
observations retain replayable raw/precision provenance when available. CSV
exports remain local analysis-only artifacts and do not modify the database.

## Boundaries

- No input automation, navigation, crawling, debugger, Activity-sheet opening,
  network inspection, cookie/storage access, or credential handling is added.
- Rounded Views, body extraction, topic tags, sequence indicators, publication
  timing, and Thread extraction must not regress.
- Structural Pattern analysis and M5 remain out of scope.

## Definition of Done

1. One-to-three post read-only DOM audit records the actual engagement-control
   forms without live source content in Git.
2. Like, Reply, Repost, and Quote deterministic extractors handle audited exact
   and rounded display forms with context proof.
3. Missingness is never written as zero, and body numbers are ignored.
4. Only missing-engagement roots can be explicitly re-enriched.
5. CSV count fields agree with stored observations.
6. Tests, repository validation, and CI pass.
7. A bounded five-post live comparison records UI/DB/CSV agreement and the
   remaining missing-engagement candidate count.
