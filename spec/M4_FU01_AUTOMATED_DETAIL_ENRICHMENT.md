# M4-FU01 — Automated Detail Enrichment

STATUS: `FAIL_AFTER_SELF_REPAIR / LIVE VIEW CAPTURE UNVERIFIED`

Contract version: `M4-FU01-AUTOMATED-DETAIL-ENRICHMENT-V1`

This independent follow-up to completed M4 does not authorize M5 Content Generation.

## Goal and human boundary

Only a post accepted through the human-selected `Pattern収集` action may enter
the detail queue. One explicit `詳細をまとめて補完` action starts a bounded
sequential batch. A dedicated worker tab may then navigate only saved
`DETAIL_PENDING` post URLs until completion or user stop.

The worker never automates Threads search, scrolling, post selection, or
general browsing. It must not navigate a normal user tab, use parallel detail
tabs, imitate human activity, evade controls, or read/store credentials,
cookies, tokens, hidden state, or DOM dumps.

## Persistent queue and state

The localhost Source Store is authoritative. A queue item is keyed by the
existing browser post identity and uses `DETAIL_PENDING`, `DETAIL_PROCESSING`,
`DETAIL_ENRICHED`, or `DETAIL_FAILED`. Evidence records batch ID, ordered item,
attempt, timestamps, bounded failure code, and source observation/detail
attempt provenance. Interrupted processing is safely retryable on the next
explicit resume. Success never overwrites prior observations.

Closed failure codes include `PAGE_TIMEOUT`, `POST_NOT_FOUND`,
`ACTIVITY_BUTTON_NOT_FOUND`, `ACTIVITY_DIALOG_TIMEOUT`, `VIEW_COUNT_NOT_FOUND`,
`THREAD_SEQUENCE_NOT_OBSERVED`, `INGESTION_FAILED`, and `EXTRACTOR_MISMATCH`.
Missing optional evidence remains unknown rather than inferred.

## Extension worker

The background service worker owns the active batch and reuses at most one
dedicated detail tab. Processing is serial. Readiness uses bounded DOM
observation, canonical permalink agreement, post-container presence, and
activity-control presence with timeout; fixed sleep alone is insufficient.

The content worker reuses the versioned M3 detail extractor and thread sequence
contract. Activity UI recognition combines visible text, ARIA semantics, role,
and local DOM context rather than generated class names. Dialog extraction
reads only visible public values. Zero and not-observed remain distinct.

## Observations and analysis integration

Detail evidence is a new immutable `POST_DETAIL` observation. Fuller visible
text creates a new browser normalized version and never overwrites search-card
evidence. Field provenance includes surface, time, extractor version, and
source identity. Observed thread nodes support multiple self replies and store
only visible root, position, reply-to, and same-author evidence.

Batch completion exposes an explicit bridge/clean-snapshot/analysis refresh
boundary; one item does not replay the whole dataset. Source text, URL, author,
metrics, and relationships remain `ANALYSIS_ONLY_SOURCE`. Generation-facing
access remains limited to `GENERATION_SAFE_PATTERN`.

## Resource and security limits

- one worker tab and one in-flight item;
- bounded queue page size, DOM wait, dialog wait, and retry count;
- canonical saved Threads post URLs only;
- existing loopback allowlist and body-size limit;
- safe errors with no page text or secret echo;
- live observations stay in ignored local `data/` paths;
- committed fixtures are synthetic or sanitized.

## Definition of Done

1. spec, change record, and tasks are SSOT;
2. queue/batch/attempt state is persistent, duplicate-safe, resumable, and isolated;
3. one explicit extension action processes only selected pending identities;
4. one dedicated detail tab is reused and normal Threads tabs are untouched;
5. DOM-ready, activity-control, dialog, and timeout behavior are tested;
6. visible view count is captured; missing metrics are not zero;
7. fuller text is appended as detail evidence with provenance;
8. observed multi-node self-reply evidence uses the existing contract;
9. receiver, extension, bridge, source-quality, and M0–M4 regressions pass;
10. credential/cookie/token leakage tests pass;
11. GitHub Actions passes;
12. HG-03 live E2E verifies at least five pending posts, one-button batch start,
    worker-tab reuse, view extraction, enriched states, and isolated failure.

Items 1–11 proceed autonomously. Item 12 is the only Human Gate and does not
authorize M5.

## Implementation evidence

- migrations 16–17 persist the queue, batch, lease, retry, and single-running-batch rules;
- the extension processes one item at a time in one dedicated inactive tab;
- the loopback receiver exposes the closed batch/claim/complete/fail protocol;
- completed batches can create a clean finalized delta snapshot through
  `sce-prepare-detail-batch` without exposing source text, URL, or author;
- local regression passes with 170 Python tests and 8 JavaScript suites.

Live Threads data, credentials, and browser state are intentionally absent from
repository evidence. GitHub Actions must pass at the current commit before HG-03.
