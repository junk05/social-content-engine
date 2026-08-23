# M4-FU03 — Post-S8 Thread Coverage Diagnostic

STATUS: `COMPLETE`

Change record: `CR-0020`.

## Scope

This follow-up pauses Thread Structural Pattern regeneration while auditing and
repairing Thread Sequence observation for the isolated 130-root post-S8 cohort.
First-Line and Post Structural results remain unchanged. M5 is not authorized.

## Cohort audit

The denominator is the same explicit post-S8 cohort used by M4-FU02. The audit
reports latest search/detail extractor versions, v6 processed roots, v6
root-only sequences, roots with one or more eligible self replies, Thread
observation status, and self-reply-count distribution. All-period totals are
kept separate.

The initial read-only audit found:

- 130 roots, all last observed by `threads_search_card_extractor_v2`;
- 0 v6 detail observations and 0 v6 Thread Sequence observations;
- 130 `DETAIL_PENDING` roots;
- 130 `NOT_OBSERVED` Thread statuses and a `0: 130` self-reply distribution.

Therefore the current CSV does not prove a v6 extraction false negative: v6
has not processed this cohort. Human-observed self-reply roots still require a
bounded live diagnostic before Thread analysis may resume.

## Relationship invariant

An eligible continuation requires both the root author and observed membership
in the author-owned branch from the root. A root-author reply below another
author's comment remains excluded. Username equality alone is never sufficient,
and timestamp proximity is not relationship evidence.

The extractor may recognize multiple DOM forms, but each form must emit a
versioned relationship-evidence code and deterministic exclusion reason. When
the relationship cannot be observed, it remains `NOT_OBSERVED`.

## Live diagnostic

HG-03 may be used for one to three post-S8 roots that a human confirms contain
self replies. The diagnostic may expose only aggregate counts, closed reason
codes, structural paths, and relationship evidence. It must not persist live
text, URL, username, cookies, storage, network responses, or credentials in Git.

For each selected root it reports visible post-node count, root count, direct
root-author candidate count, other-author branch count, root-author replies
under other-author branches, discovered/excluded/eligible counts, exclusion
reasons, and relationship evidence.

## Completion

M4-FU03 completes only after the S8 regression remains green and live evidence
shows true root-author chains included while replies below other-author branches
remain excluded. Thread Pattern regeneration remains paused until then.

## HG-03 result — 2026-08-23

PASS. The shared extractor now waits for DOM-confirmed root `1 / N` sequences
to expose their expected visible nodes before preserving the existing strict
branch rule. The post-enrichment aggregate recorded six current qualifying
roots as complete, with zero current root-only, incomplete, or re-enrichment
candidates. S8 branch regression remains green; Thread Pattern regeneration
stays paused. Source-text-free evidence is
`spec/evidence/M4_FU03_HG03_THREAD_COVERAGE_RESOLUTION.json`.
