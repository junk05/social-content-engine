# M3 — Threads Browser Collector & Detail Enricher

Status: `APPROVED`

Contract version: `M3-BROWSER-COLLECTOR-V1`

## 1. Goal

M3 lets a person select public Threads posts while browsing normally. A local
Manifest V3 Chrome extension adds one `Pattern収集` action to recognized post
cards and sends only the selected, visibly observed public fields to a
localhost receiver. Detail enrichment is a separate, user-started batch over
saved post URLs. M1 analysis and M2 feature/pattern processing are reused.

M3 does not automate search, scrolling, selection, evasion, or publication.

## 2. Authority and prior milestone boundary

M0 raw API evidence and normalized identity semantics remain authoritative.
M1 analysis contracts and M2 versioned features/pattern contracts remain
unchanged. M2 remains `IN_PROGRESS / TRUE_BLOCKER` for API-wide public search;
M3 is an additive human-selected browser observation source and does not claim
that M2's API collection target passed.

## 3. Browser observation contract

Every browser capture is an immutable observation. Required envelope fields:

- `schema_version`, `observation_type`, `source`, `post_url`;
- `source_post_id` when reliably derived, otherwise `null`;
- observed author name/username, text, timestamp and public counters;
- `media_type`, `has_image`, `has_video` when observed;
- `collection_context`, `observed_fields`, `collected_at`;
- `extractor_version` and a canonical payload SHA-256.

Each `observed_fields` entry identifies the field, exact observed value,
surface (`threads_search_card` or `threads_post_detail`), observation time and
extractor version. Missing fields are `null` or absent as defined by the
schema; they are never inferred.

The canonical post identity is a normalized Threads post URL. A reliably
derived post ID is supplemental. Repeated captures create new observations but
reuse the same normalized post identity and create a new normalized version
only when the canonical normalized payload changes.

## 4. Status model

- `COLLECTED`: search-card observation accepted;
- `DETAIL_PENDING`: detail-only fields, initially `view_count`, are missing;
- `DETAIL_ENRICHED`: a detail observation was accepted;
- `DETAIL_FAILED`: the latest explicit detail attempt failed.

Status changes do not delete observation or failure history.

## 5. Local receiver

The receiver exposes `POST /browser-ingest/threads`, binds to loopback by
default, validates a closed JSON schema, limits request size, rejects malformed
or non-Threads input, and is duplicate-safe. CORS permits only configured
Chrome-extension origins and the receiver never becomes a public service.
Credentials, cookies and access tokens are rejected fields and are never
logged or stored.

## 6. Chrome extension

The first target is an unpacked Manifest V3 Chrome-family extension. It uses a
versioned extractor (`threads_search_card_extractor_v1`) isolated from button
injection and transport. Recognition combines stable evidence such as Threads
permalinks, `time`, semantic links and accessibility attributes; it must not
depend on one generated CSS class.

A `MutationObserver` handles newly added cards. Initial content, SPA
navigation, infinite-scroll additions and repeated scans must not add duplicate
buttons. Successful ingestion changes only that card to `✓ 収集済み`.

The extension stores no Threads password, cookie or token and sends no
arbitrary page data or automatic browsing commands.

## 7. Detail enrichment

Detail enrichment is explicitly user-started and processes only
`DETAIL_PENDING` saved URLs. M3 V1 prioritizes `view_count`; updated visible
like/reply/repost counts and observed relationships may be captured without
inference. Each URL succeeds or fails independently. Failures store URL,
bounded failure type, extractor version and attempt time, but never browser
credentials or cookies.

Initial live enrichment may use the extension on an already opened detail page
or a user-controlled local batch. It must not silently navigate Threads or
imitate human activity.

## 8. Analysis integration

Accepted browser observations derive the existing normalized-post shape.
Browser posts use the existing M1 Analyzer, First-Line and Parent-Ending
extractors, Pattern Instance and Pattern Miner. No browser-specific analyzer or
parallel text semantics are introduced.

## 9. Security and data policy

- public information visible on the selected Threads page only;
- localhost receiver by default and bounded body size;
- explicit extension-origin allowlist;
- no password, cookie, token, DOM dump or hidden application state;
- no automatic search, scrolling, bulk selection or anti-detection behavior;
- live observations, raw page evidence and report excerpts stay under ignored
  local `data/` paths; committed fixtures are synthetic or sanitized.

## 10. Definition of Done

M3 is complete only when:

1. the unpacked extension loads in Chrome;
2. initial and dynamically inserted Threads result cards are recognized;
3. exactly one `Pattern収集` action appears per recognized card;
4. selected public fields reach the validated localhost receiver;
5. accepted cards show `✓ 収集済み`;
6. repeated collection preserves N observations and one normalized identity;
7. post URL and field-level provenance are stored;
8. missing views produce `DETAIL_PENDING`;
9. a user-started detail batch isolates per-post failures;
10. at least one live detail page yields an observed `view_count`;
11. detail observation history links to the existing post;
12. at least ten human-selected live posts are ingested;
13. browser-ingested posts run through M1/M2 without alternate semantics;
14. schemas, fixtures, tests, lint, typecheck and regression pass;
15. GitHub Actions passes on Python 3.9 and 3.12;
16. no credential, cookie or sensitive live raw evidence is committed.

Items 1, 10 and 12 require HG-03. M3 completion is forbidden until every item
passes with committed sanitized evidence.

## 11. Deferred

Chrome Web Store publication, automatic updates, Firefox/Safari, dashboards,
scheduled detail crawling, automated search/scroll/selection, content
generation, publishing and anti-detection behavior are deferred.
