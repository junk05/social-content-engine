# M4-FU04 — Collected Post Management

STATUS: `COMPLETE`

Change record: `CR-0021`.

## Goal

Provide a local, human-reviewable list of collected canonical root posts so a
deleted, vanished, or permanently unavailable source can be excluded from
Detail Enrichment without deleting Source Store evidence.

## Source and UI contract

The Extension options page reads only the loopback receiver and shows one row
per canonical root selected through `Pattern収集`. Each row may show collection
time, author username, canonical URL, detail status, last closed error, rounded
Views when observed, and clean self-reply count when known.

MVP filters are `ALL`, `DETAIL_PENDING`, `DETAIL_FAILED`, `DETAIL_ENRICHED`, and
`EXCLUDED`. Ordering is deterministic and newest-first. The list remains local,
is never a Generation-facing interface, and never exposes source text.

## Exclusion semantics

Current queue state records:

- `enrichment_excluded`;
- `exclusion_reason = USER_EXCLUDED_SOURCE_UNAVAILABLE`;
- `excluded_at`.

Every exclude or re-enable action also appends an immutable audit entry. Source
observations, attempts, failures, metrics, relationships, and identities remain
untouched. Exclusion is rejected while an item is actively processing.

Pending-list and batch-claim selection require `enrichment_excluded = false`.
An explicit `再補完` action re-enables an excluded item, clears only current
closed queue errors, and returns the queue item to `DETAIL_PENDING`; historical
attempt/failure evidence is retained. Automatic exclusion is out of scope.

## Security

List and action endpoints remain loopback-only and exact Extension-origin-only.
Inputs use a closed action/reason contract and canonical saved Threads URLs.
Cookies, credentials, browser storage, page content, and arbitrary remote URLs
are not accepted.

## Definition of Done

1. additive migration preserves existing Source Store and queue evidence;
2. list is one canonical root per row and supports the closed status filter;
3. exclusion is audited and excluded items cannot be listed as pending or claimed;
4. re-enrich/re-enable is explicit, audited, and duplicate-safe;
5. Extension renders the list and both row actions safely;
6. repository, receiver, transport, UI, security, and M4-FU01 regressions pass;
7. completed logical commits are pushed to `main` and M5 remains unauthorized.

## Verification

- additive migration 24 preserves queue/source rows and appends immutable action history;
- excluded roots are absent from pending URL selection, failed retry, and batch claim;
- explicit requeue re-enables the root without deleting observations, attempts, or failures;
- receiver and Extension contracts reject unknown actions, unsafe URLs, and malformed list rows;
- local Extension suites, lint, mypy, repository validation, and 189 Python regressions pass.
