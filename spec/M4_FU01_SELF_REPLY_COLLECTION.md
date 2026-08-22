# M4-FU01-S8 — Self-Reply Content Collection

STATUS: `COMPLETE`

Contract version: `M4-FU01-SELF-REPLY-COLLECTION-V2`

## Scope

One human-selected root remains the only collection trigger. During its existing
detail enrichment, the shared visible-DOM extractor may append detail observations
for visible same-author reply permalinks. This is an extension of the existing
M4-FU01 Thread Sequence path, not a new crawler or pipeline.

The collector:

- emits the root at sequence position 0;
- requires both root-author identity and observed membership in the contiguous
  root-author-owned conversation branch;
- traverses from the root in visible conversation order, appending consecutive
  root-author nodes at positions 1, 2, 3, and beyond;
- stops the branch permanently at the first other-author node and never rejoins
  a later root-author reply below that branch;
- stores each reply as an immutable `POST_DETAIL` observation with the existing
  source identity, text, timestamp, counters, observed time, extractor version,
  field provenance, and payload hash contract;
- stores root, node, optional reply-to identity, sequence position, and observed
  same-author state plus closed `relationship_evidence` through
  `browser_thread_sequence_observations`;
- leaves `reply_to_post_url` null unless the visible surface directly exposes the
  relationship; DOM order or wording alone never creates an edge;
- never appends other-author general reply details;
- deduplicates visible permalinks within extraction and reuses existing identity
  and normalized-version semantics across repeated collection.

Username equality or timestamp proximity alone is not relationship evidence.
`source_post_id`, an explicit parent edge, or another field that is not visible
remains null/unknown. Absence is not inferred as false.

## Data and generation boundary

Root and self-reply text, URL, author, and source-specific wording remain
`ANALYSIS_ONLY_SOURCE`. Existing Source Store and Thread Sequence provenance may
be reused without migration. Pattern Library artifacts contain only abstract
structural components and aggregate evidence. Generation-safe DTOs continue to
exclude source observations and identifiers.

## Analysis contract

A root-only node is not a self-reply transition. `PARENT_TO_SELF_REPLY` and
`OBSERVED_SELF_REPLY_TRANSITION` require an observed node with
`same_author_as_root=true` and `sequence_position>0`.

The stored graph supports later deterministic sequence analysis such as:

`ROOT -> SELF_REPLY_1 -> SELF_REPLY_2 -> ...`

and abstract roles such as:

`OPEN_LOOP -> EXPLANATION -> ESCALATION -> PAYOFF -> CTA`.

This follow-up does not assign those semantic roles, implement generation, or
authorize M5.

## Definition of Done

1. shared detail extractor emits a compact root plus same-author sequence only;
2. zero, one, or many self replies are supported without a one-to-one model;
3. self-reply `POST_DETAIL` observations precede relationship persistence;
4. unknown reply-to edges remain null;
5. duplicate, resume, pacing, and failure-isolation behavior remains intact;
6. source/generation isolation and regressions pass;
7. existing stored self-reply detail and sequence evidence remains reusable;
8. HG-03 verifies one selected live root with at least one visible self reply.

Items 1–7 proceed autonomously. Item 8 reuses the existing browser-action Human
Gate and creates no new gate.

The existing local Source Store audit found 43 non-root same-author sequence
nodes, all with corresponding `POST_DETAIL` source observations. No explicit
parent edges were present, so none are invented. Legacy positions retain their
observed full-DOM ordinals; new v5 observations use compact self-reply positions.
Only aggregate sanitized evidence is committed in
`spec/evidence/M4_FU01_S8_EXISTING_EVIDENCE_AUDIT.json`.

The first HG-03 result is superseded. Human review established that the stored
six-node observation contained one root, three true root-author continuations,
and two later root-author replies below other-author branches. The immutable bad
observation remains audit evidence but is ineligible for clean Thread Sequence
analysis. Sanitized findings are recorded in
`spec/evidence/M4_FU01_S8_FALSE_POSITIVE_AUDIT.json`. S8 returns to COMPLETE only
after a v2 live result contains exactly one root and three eligible self replies.

Extractor v6 emits `ROOT_DETAIL_PAGE` for the root and
`DOM_CONTIGUOUS_ROOT_AUTHOR_CHAIN` only for the contiguous root-author prefix.
Migration 23 leaves historical rows nullable, so v5 username-only observations
remain immutable but are excluded from clean structural self-reply eligibility.

The repeated HG-03 live E2E passed with exactly one root and three eligible
self replies. All three child details were stored, positions were compact, and
no root-author replies below other-author branches entered the sequence. The six
historical v5 rows remain immutable with null relationship evidence and are not
eligible. Sanitized evidence is in
`spec/evidence/M4_FU01_S8_BRANCH_LIVE_VERIFICATION.json`.
