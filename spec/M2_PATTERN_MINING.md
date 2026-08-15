# M2 — Cross-post Pattern Mining & Dataset Expansion

STATUS: HUMAN-GATE APPROVED
SPEC_ID: M2-PATTERN-MINING-V1

M2 expands the evidence dataset and derives reproducible cross-post structural
patterns from M1 analysis. It does not generate content, publish content,
predict virality, profile creators, or integrate Fortune Engine.

## 1. Goals and order of work

M2 MUST keep collection moving independently of Pattern Miner completion.
Implementation priority is:

1. build bounded multi-query `TOP` and `RECENT` collection;
2. preserve exact raw evidence and version normalized derivatives;
3. collect 100 unique public posts when the permitted API reasonably allows it;
4. batch M1 analysis over a frozen dataset;
5. extract First-Line and Parent-Ending features;
6. create reproducible Pattern Instances and cross-post Pattern candidates;
7. rank by evidence support and generate a human-review report.

The target is 100 unique posts and the hard ceiling is 200 unique posts. A live
run MUST stop at the ceiling. If Meta API behavior, App mode, permissions,
coverage, or rate constraints make 100 unreasonable, M2 records the measured
result and stop reason and may adjust the numeric DoD without inventing data.

## 2. Official API boundary

Meta's official Threads Postman workspace documents:

- `GET /keyword_search`;
- `search_type=TOP|RECENT`;
- `search_mode=KEYWORD|TAG`;
- `q`, `fields`, `limit`, `since`, and `until`;
- a response envelope with `data[]` and `paging.cursors.before/after`;
- `limit=50` as an example, not as a documented maximum.

The initial collector therefore uses a configured page size no greater than 50.
The following remain `UNKNOWN` until captured live or documented explicitly:

- Keyword Search maximum page size and total result limit;
- cursor lifetime, ordering stability, completeness, and quota numbers;
- TOP ranking semantics;
- whether Keyword Search exposes engagement counts;
- whether `/{thread_id}/insights` is permitted for another account's public post.

Post Insights documents `views`, `likes`, `replies`, `reposts`, `quotes`, and
`shares`, but this is not evidence that those metrics are available for an
arbitrary public Keyword Search result. M2 performs a bounded spike and records
success or rejection. Missing metrics remain absent/`UNKNOWN`.

Official references:

- https://www.postman.com/meta/threads/overview
- https://www.postman.com/meta/threads/request/34203612-b3b2c12a-7ce6-4d86-a3c6-6d31e3b66ea1
- https://www.postman.com/meta/threads/request/ndeeu6p/get-post-insights
- https://developers.facebook.com/docs/threads/keyword-search
- https://developers.facebook.com/docs/threads/changelog

## 3. Collection policy

Initial keyword families MUST span at least five of these approved genres:

- romance (`恋愛`)
- relationships (`人間関係`, `男女`)
- psychology (`心理`)
- fortune telling (`占い`)
- beauty (`美容`)
- work (`仕事`)
- money (`お金`)
- self-development (`自己啓発`)
- parenting (`子育て`)
- health (`健康`)
- life hacks (`ライフハック`)

Every configured family SHOULD run both `TOP` and `RECENT`. Collection is
sequential and low-volume. Defaults:

- target unique posts: 100;
- hard ceiling: 200;
- page size: 25 for canary, configurable up to 50;
- canary: one `RECENT` page and its next cursor, then one `TOP` page;
- bounded requests per invocation;
- configurable inter-request interval of at least two seconds for live runs;
- no deliberate 429 generation.

Stop reasons are closed values: `TARGET_REACHED`, `HARD_CAP_REACHED`,
`REQUEST_CAP_REACHED`, `NO_NEXT_CURSOR`, `EMPTY_PAGE`, `REPEATED_CURSOR`,
`HTTP_ERROR`, `INVALID_RESPONSE`, or `INTERRUPTED`.

Checkpoints MUST exclude credentials and preserve query, search type, time
window, opaque cursor, observed/unique counts, and last completed request.

## 4. Evidence and deduplication boundaries

M0 semantics remain authoritative:

- every HTTP call creates one immutable `collection_runs` row containing exact
  response bytes and SHA-256;
- every observed item creates a run-linked `raw_posts` observation;
- raw responses and observations are never deduplicated away;
- normalized identity remains unique by `(source, source_post_id)`.

M2 adds normalized version history before expanded ingestion:

- a mechanically normalized payload has a canonical hash;
- identical payload hash reuses the existing normalized version;
- a changed payload creates version `N+1`;
- prior analysis retains a foreign key to the exact normalized version used;
- `normalized_posts` remains the current identity/read model.

Duplicate reporting distinguishes same-page, cross-page, cross-query,
TOP/RECENT, and re-observation overlap. Account identity is deduplicated only by
observed source account ID or username; missing identity is not inferred.

## 5. Batch and dataset provenance

M2 adds versioned records for:

- collection batch, ordered query specification, pages, and stop summary;
- numbered transactional schema migrations with migration hash;
- normalized post versions and normalizer version;
- frozen dataset snapshots and ordered members;
- analysis batches and item-level status/retry provenance;
- metric observations when and only when returned by an official API.

A dataset snapshot is mutable only while `DRAFT`. `FINALIZED` snapshots are
immutable. Dataset membership points to a normalized version and selected raw
observation, not merely the mutable current row.

The provenance chain is:

`batch config/query hash -> collection run -> exact response hash -> raw item
hash -> normalizer/version hash -> dataset selection hash -> Analyzer Input hash
-> analysis output hash -> feature extraction hash -> Pattern Instance -> Pattern`.

Canonical serialization and hash algorithm versions MUST be explicit.

## 6. Metrics

Metrics are append-only observations, not columns overwritten on a normalized
post. A metric observation contains source post ID, metric name, non-negative
value, observed time, API field/unit, collection or raw evidence reference, and
collector version.

Zero is a valid observed value. Absence is `UNKNOWN`, not zero. `tap`, profile
visit, silent engagement, deep read, and other unavailable behavior MUST NOT be
created or inferred.

The data model must permit future comparisons without asserting success:

- `absolute` observed metrics;
- `account-relative` only when sufficient same-account observations and a valid
  denominator exist;
- `conversation` only from observed reply/conversation data;
- `breakout` remains a future derived classification with explicit versioning.

`likes >= 5000` is not the definition of viral and is not an M2 ranking rule.

## 7. Batch Analyzer

An analysis batch targets one finalized dataset snapshot and pins analyzer,
taxonomy, prompt, model, parameters, and normalized versions. It wraps the M1
append-only analysis boundary; it does not replace it.

- successful identical analyses may be reused;
- failed items retain error provenance and may be retried;
- restart skips completed items deterministically;
- reuse identity includes model provider and normalized version ID;
- credentials are never batch metadata.

## 8. First-Line Intelligence

First-Line extraction is deterministic over M1's NFC-normalized text. It stores
the first non-empty line as a source span reference, not as Pattern Library text.

Required instance features:

- line availability and source span;
- character count and terminal-mark family;
- `hook_family` and `hook_subtype` from closed, versioned vocabularies;
- bounded ordinal scores for `curiosity_gap`, `self_relevance`,
  `target_specificity`, `emotional_intensity`, `contrarian_level`, and
  `read_more_pressure`;
- `expected_action` from a closed vocabulary;
- overlapping M1 action/structure labels.

Scores describe explicit text evidence, not predicted performance. Unknown or
unsupported values use `UNKNOWN`; no model may silently fill them.

## 9. Parent-Ending Intelligence

Parent Ending uses `thread_relationships` as the relationship SSOT. It stores
span/hash references for the parent last non-empty line and last two or three
non-empty lines when the parent text is observed.

Required fields:

- `availability`: `OBSERVED`, `NO_PARENT`, `PARENT_TEXT_UNAVAILABLE`, or
  `RELATIONSHIP_AMBIGUOUS`;
- parent source-post reference when observed;
- last-line and last-2/3-line span references and parent text SHA-256;
- terminal-mark family;
- bounded `open_loop_score`, `closure_score`, and `continuation_desire`;
- closed `cliffhanger_technique`;
- overlapping version-compatible parent action/structure labels.

No parent meaning is inferred when relationship or parent text is unavailable.

## 10. Pattern Instance and Pattern boundary

A Pattern Instance represents one successful analysis plus one extractor
version. It stores feature values, source/analysis references, membership,
input hashes, and evidence span/hash references. It may reference a source post
but MUST NOT copy source text or evidence quotes.

A Pattern is a multi-post abstraction. `patterns.payload_json` MUST NOT contain:

- post text or evidence quote;
- username, permalink, or author profile data;
- a single-post free-form summary presented as a general rule.

A Pattern contains only a versioned closed feature signature, aggregate support,
coverage, ranking provenance, and review status. At least two distinct source
posts are required to promote a cluster to a Pattern candidate.

M2 V1 clustering is deterministic exact-signature clustering:

1. normalize and sort closed-vocabulary feature labels;
2. canonicalize the feature signature;
3. use its SHA-256 as `cluster_key`;
4. set exact membership distance to zero;
5. preserve unclustered singletons as instances but not Patterns.

Approximate/embedding clustering is deferred until a separately versioned spec.

## 11. Ranking and report

Ranking is evidence-support ranking, not virality prediction. The deterministic
ordering is:

1. member support descending;
2. distinct observed author support descending, with coverage shown;
3. Parent-Ending evidence support descending;
4. feature completeness descending;
5. `pattern_key` ascending as final tie-breaker.

Every Pattern stores miner/extractor/taxonomy versions, canonical signature hash,
sorted instance-set hash, observation window, and member counts.

The human-review Pattern Report may join source text at generation time for
review, but source text is not copied into Pattern storage. The report includes
at least ten Pattern candidates when the dataset supports them, evidence links,
missing-data warnings, rank provenance, and `PENDING/APPROVED/REJECTED` review
state. M2 does not use approval to trigger generation or publishing.

## 12. Security and privacy

- use only M0-permitted public data;
- do not enrich posts with private, purchased, or sensitive personal data;
- do not persist access tokens or model keys;
- commit only synthetic or sanitized fixtures, never live raw responses;
- retain observation/inference/unknown distinctions;
- do not diagnose psychology or infer protected/sensitive traits.

## 13. Task execution rule

Each Task follows:

`IMPLEMENT -> targeted tests -> review -> regression -> atomic commit -> push -> NEXT TASK`

No Task may carry uncommitted changes into the next Task. Collector, Data,
Intelligence, and QA work may run in parallel only where file ownership and
dependencies do not overlap.

## 14. Definition of Done

M2 V1 is complete when:

1. at least 100 real public posts are captured, or a measured API constraint
   evidence record justifies an approved numeric adjustment;
2. at least five genres and both TOP/RECENT are represented when API coverage
   permits;
3. collection batches are bounded, resumable, and provenance-complete;
4. raw observations remain immutable and normalized versions are reproducible;
5. obtainable public metrics are stored as observations and unavailable metrics
   remain UNKNOWN;
6. a finalized dataset snapshot can be batch-analyzed with M1;
7. First-Line and Parent-Ending features are versioned and stored;
8. Pattern Instances and deterministic cluster membership are reproducible;
9. at least ten cross-post Pattern candidates exist, each with two or more
   source-post evidence references, or dataset evidence proves this threshold
   unsupported and the DoD is explicitly adjusted;
10. deterministic ranking and a human-review Pattern Report are generated;
11. raw/normalized/analysis/feature/pattern provenance validates end-to-end;
12. M0 and M1 regression, migration tests, security checks, and CI pass on
    Python 3.9 and 3.12;
13. SSOT marks M2 `COMPLETE` only after items 1–12 pass.

## 15. Deferred

- content generation and automatic publishing;
- virality or engagement prediction;
- approximate/embedding clustering;
- creator profiling;
- Fortune Engine integration;
- production deployment and dashboards.
