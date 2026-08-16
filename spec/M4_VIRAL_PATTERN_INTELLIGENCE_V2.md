# M4 Viral Pattern Intelligence V2 — Revision Contract

STATUS: `APPROVED BY CR-0003`

This revision responds to the rejected initial HG-04 report. It supplements
`M4_VIRAL_PATTERN_INTELLIGENCE.md`; its requirements take precedence where they
conflict.

## 1. Root-cause boundary

The initial 92-post snapshot contains short single-line search-card text for
every member. M4 V2 must not manufacture body, relationship, or metric evidence
that was not observed. It may read normalized text during analysis, but source
text remains forbidden in persistent Pattern payloads and committed evidence.

## 2. Multi-label First-Line taxonomy

First-Line extraction is a deterministic, closed multi-label classifier. A
feature may contain zero or more sorted labels from each dimension:

- rhetorical form: `QUESTION`, `ASSERTION`, `CONTRARIAN_CLAIM`,
  `EXPECTATION_REVERSAL`, `WARNING`, `CONFESSION`, `REVELATION`, `NUMBER_LIST`;
- audience and tension: `READER_TARGETING`, `IDENTITY_CALLOUT`,
  `EMOTIONAL_VALIDATION`, `PAIN_PROBLEM_ACTIVATION`,
  `DESIRED_FUTURE_ACTIVATION`, `AUTHORITY_EXPERIENCE`, `TABOO_SECRET`;
- continuation mechanics: `CURIOSITY_GAP`, `INCOMPLETE_INFORMATION`,
  `IMPLIED_BENEFIT`, `IMPLIED_THREAT`, `URGENCY`, `SURPRISE`;
- certainty: exactly one of `CERTAIN`, `QUALIFIED`, `AMBIGUOUS`, `UNKNOWN`.

Each non-empty label needs deterministic span/hash evidence or an inherited
M1/M2 evidence reference. No free-form interpretation or original phrase is
stored in the Pattern layer.

## 3. Body, ending, and action hypotheses

Body roles are independently classified from the full normalized text available
to the analyzer, using the closed labels `SETUP`, `TENSION`, `REVERSAL`,
`EXPLANATION`, `ESCALATION`, `VALIDATION`, `PAYOFF`, and `TRANSITION`.
`UNKNOWN` is used only when the available text cannot support a role.

Action hypotheses are stored with `PSYCHOLOGY_HYPOTHESIS`, never as observed
behavior: `CONTINUE_READING`, `TAP_OPEN_DETAIL`, `READ_SELF_REPLY`,
`REPLY_OR_COMMENT`, `SELF_DISCLOSURE_REPLY`, `SAVE`, `SHARE`, `PROFILE_VISIT`,
and `FOLLOW`. Unsupported hypotheses remain absent or `UNKNOWN`.

Open-loop analysis includes both Parent Ending when a relationship is observed
and post-internal information gap/unresolved tension when its span is within
the normalized text. The two evidence modes are kept distinct.

## 4. Decomposed Pattern families and ranking

First-Line, Body, Ending, Action, and Sequence Patterns are independently
aggregated before combinations are reported. An actionable Pattern requires at
least two distinct source posts and at least one non-`UNKNOWN`/non-`NONE`
mechanism. Clusters dominated entirely by `UNKNOWN` or `NONE` are reported only
as coverage diagnostics and cannot rank as actionable Patterns.

Each report item includes its closed mechanism set, abstract formula composed
only of closed labels, support/evidence count, deterministic confidence, metric
coverage, and an explicitly hypothetical psychological effect.

## 5. Metrics and recapture

Performance association is metric-specific. Every metric reports its own
coverage; one observed Views value cannot stand in for likes, replies, reposts,
quotes, or shares. Missing remains `UNKNOWN`.

M3 may be extended to capture visible rendered full post text and exact visible
counters only after tests. Recollecting any live observation requires HG-03 and
human selection; M4 must not automate navigation, selection, or collection.

## 6. Required replay and gate

Re-run M4 V2 on the same snapshot first. If current evidence remains
insufficient, record the gap and request the smallest HG-03 recapture needed.
Generate a revised local report and repeat HG-04. M4 remains incomplete and M5
remains forbidden until that review is approved.
