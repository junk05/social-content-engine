# M4 — Viral Pattern Intelligence

STATUS: HUMAN-GATE APPROVED
SPEC_ID: M4-VIRAL-PATTERN-INTELLIGENCE-V1

## 1. Goal

M4 turns the M3 browser dataset and the existing M1/M2 analysis into a
versioned, reviewable **Viral Pattern Intelligence** layer. It identifies
reusable rhetorical mechanisms, not posts to copy and not rules that guarantee
performance.

The initial run uses the 92 canonical human-selected browser posts frozen in
M3 dataset snapshot 2. It produces a local, human-readable
`VIRAL_PATTERN_REPORT` before any future content-generation work begins.

M4 does not generate, publish, schedule, rank creators, or claim that a
pattern causes engagement.

## 2. Core boundaries

- Source post text remains only in normalized evidence and runtime review
  artifacts under ignored `data/` paths. It MUST NOT be copied into M4 Pattern
  storage, committed reports, abstract formulas, or template fields.
- A Pattern is eligible only with at least two distinct source posts. One-post
  observations remain instances or `EMERGING`, never a reusable general rule.
- `likes`, `replies`, `reposts`, `quotes`, `shares`, and `views` are used only
  when explicitly observed with field provenance. Missing values are
  `UNKNOWN`, never zero or imputed.
- `tap`, profile visit, silent engagement, deep-read duration, saves, follows,
  and shares without an observed counter remain `UNKNOWN`.
- Performance association is descriptive and dataset-relative. It is neither a
  causal estimate nor a virality prediction.
- M4 preserves M0 raw, M1 analysis, M2 feature, M3 browser-observation, and
  normalized-data semantics. It adds derived records only.

## 3. Inputs and provenance

Each M4 run pins:

- one `FINALIZED` dataset snapshot and its ordered normalized-post versions;
- M1 analyzer/taxonomy/prompt/provider/model/parameter versions;
- M2 First-Line and Parent-Ending extractor versions;
- the M4 taxonomy, derivation, performance, sequence-miner, and report
  versions;
- selected browser-observation IDs and field-level metric provenance;
- canonical input hashes for every derived instance and aggregate.

The provenance chain is:

`browser observation -> normalized version -> M1 run -> M2 first-line / parent-ending
-> M4 hook/body/action/sequence instance -> observed performance snapshot
-> aggregate pattern -> VIRAL_PATTERN_REPORT`.

## 4. First-Line Hook Intelligence

M4 derives, but does not alter, the M2 First-Line feature. It records closed,
evidence-backed fields:

- inherited `hook_family`, `hook_subtype`, terminal mark, curiosity gap,
  specificity, emotional tension, contrarian level, self relevance and
  expected action;
- `surprise_signal`: `PRESENT | ABSENT | UNKNOWN`;
- `identity_targeting`: `DIRECT | GROUP | NONE | UNKNOWN`;
- `information_state`: `COMPLETE | INCOMPLETE | UNKNOWN`;
- `implied_outcome`: `BENEFIT | THREAT | MIXED | NONE | UNKNOWN`;
- `certainty_mode`: `CERTAIN | QUALIFIED | AMBIGUOUS | UNKNOWN`;
- `continue_reading_mechanisms[]`: sorted closed labels from
  `QUESTION_GAP`, `WITHHELD_REASON`, `CONTRARIAN_CLAIM`,
  `DIRECT_RELEVANCE`, `EMOTIONAL_TENSION`, `PROMISED_PAYOFF`, and `NONE`.

These labels describe text-supported rhetorical mechanisms, not actual reader
motivation. Every non-`UNKNOWN` M4 field has a deterministic source-span/hash
reference or an inherited M2 feature reference.

## 5. Body, Ending, and expected-action intelligence

M4 derives a closed sequence without inventing a narrative outline:

- `body_roles[]`: sorted subset of `SETUP`, `TENSION`, `REVERSAL`,
  `EXPLANATION`, `ESCALATION`, `VALIDATION`, `PAYOFF`, `TRANSITION`, and
  `UNKNOWN`, mapped only from M1 observable structure/action labels and their
  evidence spans;
- inherited Parent-Ending closure/open-loop/continuation/cliffhanger fields;
- `expected_reader_actions[]`: hypotheses from the closed vocabulary
  `CONTINUE_READING`, `TAP_SELF_REPLY`, `REPLY_OR_COMMENT`, `PROFILE_VISIT`,
  `SAVE_OR_SHARE`, `FOLLOW`, `NONE`, and `UNKNOWN`.

Expected reader actions are marked `HYPOTHESIS`; M4 does not assert that they
occurred. `TAP_SELF_REPLY`, profile visit, save/share, and follow are never
recorded as observed performance without explicit source evidence.

## 6. Sequence Pattern and abstraction

A M4 sequence signature is a canonical closed object:

`Hook mechanism -> Body roles -> Parent ending -> Expected reader actions`.

Each supported cluster stores a deterministic signature hash and ordered member
input-set hash, member and distinct-source support counts, and an abstract
formula made only of closed labels. `EMERGING` is support below two and
`REPEATED` is support of two or more. Confidence is `LOW | MEDIUM | HIGH`,
derived only from support/coverage and never from an asserted causal effect.

Original wording, quote text, usernames, permalinks, and free-form single-post
summaries are forbidden in persistent Pattern payloads.

## 7. Performance association

M4 materializes append-only metric snapshots from browser field observations.
For each metric it records observation ID, field name, value, observation time,
surface, extractor version, and canonical metric-input hash.

For a dataset snapshot, M4 may show absolute observed values with coverage,
deterministic dataset-relative percentile/cohort position among posts with the
same observed metric, and Pattern-level medians/coverage. Association labels
are `DESCRIPTIVE_ONLY`, `INSUFFICIENT_COVERAGE`, or `UNKNOWN`.

No threshold defines “viral.” Cross-metric totals or composite scores are not
created unless every component and normalization contract is separately
versioned in a later approved spec.

## 8. VIRAL_PATTERN_REPORT

The local runtime report includes, when supported by evidence:

- Top First-Line Patterns;
- Top Open-Loop Patterns;
- Top Action Patterns;
- Hook × Ending combinations;
- repeated and emerging patterns;
- performance-associated patterns with metric coverage and descriptive caveat;
- evidence counts, confidence, provenance, and representative **abstract**
  structures.

Runtime review may join a bounded source excerpt only for a human reviewer.
The persisted M4 Pattern records and any committed artifact remain text-free.
If the initial dataset does not support a section, the report states
`INSUFFICIENT_EVIDENCE` rather than fabricating a ranking.

## 9. Human Gate

After the first report over M3 snapshot 2, stop at `HG-04` for human review of
Pattern quality. The reviewer decides whether abstractions are useful,
over-generalized, or need taxonomy refinement. M5 Content Generation is
forbidden until this gate is recorded as approved in a later milestone.

## 10. Definition of Done

M4 is complete only when:

1. versioned M4 contracts and migrations preserve M0–M3 semantics;
2. deterministic Hook, Body, Ending, Action, and sequence instances exist;
3. persistent Pattern payloads reject source text, quotes, identity and
   free-form copyable templates;
4. Pattern support requires two distinct source posts;
5. metric snapshots preserve observed values, zero, unknown, and field-level
   provenance;
6. performance views distinguish absolute, dataset-relative, and unavailable
   metrics without causal claims;
7. `VIRAL_PATTERN_REPORT` covers the sections in §8 or marks insufficient
   evidence;
8. the initial M3 92-post report is generated locally and reviewed at HG-04;
9. deterministic replay, negative leakage, metric-coverage, M0–M3 regression,
   lint, typecheck, schema validation, and CI pass;
10. no live post text, URLs, credentials, cookies, tokens, or raw browser
    evidence is committed.

## 11. Deferred

M4 defers LLM/free-form naming, embeddings, causal inference, creator ranking,
content generation, automatic publishing, A/B experiments, and any external
analytics not already observed through the approved M3 boundary.
