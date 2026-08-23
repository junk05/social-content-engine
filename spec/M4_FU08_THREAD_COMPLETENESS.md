# M4-FU08 — Thread Sequence Completeness from Observed Indicators

STATUS: `IN_PROGRESS`

Change record: `CR-0025`.

## Purpose

A DOM-confirmed root indicator such as `1 / 4` is strong evidence that the
visible root belongs to a four-node author-owned sequence. It is not evidence
of any individual reply edge. This follow-up makes that distinction explicit:
the existing branch-aware extractor must run, and its observed outcome is
recorded as an append-only completeness assessment.

## Root rule

For a canonical root with an observed indicator where `thread_position = 1`
and `thread_total > 1`, the shared Detail Enrichment path must submit a Thread
Sequence observation and an extraction diagnostic. It must not finish with an
unqualified root-only sequence.

The only eligible continuation nodes remain consecutive root-author nodes with
`DOM_CONTIGUOUS_ROOT_AUTHOR_CHAIN` evidence. A root-author reply after an
other-author boundary remains excluded.

## Completeness assessment

The receiver records one immutable assessment for each root detail observation:

- `NOT_APPLICABLE`: no qualifying root `1 / N` indicator was observed;
- `COMPLETE`: captured eligible node count equals `thread_total`;
- `THREAD_CHILDREN_NOT_CAPTURED`: only the root was captured for `N > 1`;
- `INCOMPLETE_THREAD_EXTRACTION`: one or more, but fewer than `N`, eligible
  nodes were captured.

The assessment includes expected/captured node counts and sanitized diagnostic
counts/reason codes. It does not store source text, URLs, usernames, cookies,
credentials, or raw DOM.

Incomplete qualifying roots are not considered normal completed Thread
extractions. Their already-saved detail observation remains immutable, while
the queue is safely returned to `DETAIL_PENDING`; its latest immutable
assessment is the `THREAD_REENRICH_PENDING` equivalent for a later explicit
batch. Excluded or currently
processing roots are never altered.

## Recovery and audit

An idempotent local recovery identifies latest root details with `1 / N`,
`N > 1`, and fewer than `N` eligible captured nodes (including legacy rows
without an assessment). It requeues only those non-excluded roots. The audit
reports indicator roots, complete/incomplete assessment counts, root-only
candidate counts, and re-enrichment candidate count without mixing Thread
Pattern analysis.

## Boundaries

- The indicator verifies existence and expected size only; it never supplies a
  reply edge, author match, or branch membership.
- Original source text remains analysis-only and absent from pattern artifacts.
- Historical incorrect or incomplete observations remain immutable audit
  evidence.
- M5 and Thread Structural Pattern regeneration remain unauthorized.

## Definition of Done

1. qualifying roots always run shared branch-aware child exploration;
2. complete, root-only, and incomplete outcomes are persisted distinctly;
3. incomplete qualifying roots return to a resumable re-enrichment queue;
4. recovery is idempotent and does not touch excluded/processing roots;
5. audit reports the requested aggregate counts;
6. branch-regression, full test suite, validation, and CI pass.
