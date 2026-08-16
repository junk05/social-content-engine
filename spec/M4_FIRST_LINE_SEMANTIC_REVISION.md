# M4 First-Line Semantic Revision

STATUS: `APPROVED REVISION UNDER CR-0005`

M4 remains `IN_PROGRESS`. M5 Content Generation remains prohibited.

## Root-cause protocol

Before semantic classification, First-Line extraction excludes only an exact
browser-rendered date metadata line (`YYYY/MM/DD` or `YYYY-MM-DD`). It does not
discard a natural-language line merely because it contains a number or date.
The selected line continues to retain only span/hash evidence in persisted M4
features; source text never enters a Pattern artifact or report.

## Semantic coverage boundary

`ASSERTION` is a rhetorical form, not a semantic conclusion. It may coexist
with semantic/psychological mechanisms. Deterministic rules may promote a
mechanism only when a closed rule has span/hash evidence. Candidate axes are:

`SELF_RELEVANCE`, `READER_TARGETING`, `PAIN_ACTIVATION`,
`DESIRE_ACTIVATION`, `IDENTITY`, `EXPECTATION_REVERSAL`, `CURIOSITY`,
`INFORMATION_GAP`, `SPECIFICITY`, `NOVELTY`, `IMPLIED_BENEFIT`,
`LOSS_AVERSION`, `AUTHORITY_EXPERIENCE`, `SOCIAL_PROOF`,
`EMOTIONAL_VALIDATION`, `URGENCY`, `TABOO_SECRET`, `DIRECT_ADDRESS`,
`IMPORTANCE_SIGNAL`, and `LIST_NUMBER_STRUCTURE`.

No label may be inferred solely from a generic form such as `ASSERTION`.

## Escalation to an LLM semantic classifier

If the aggregate audit shows that deterministic span-backed rules leave a
material generic residual, the required decision is `LLM_SEMANTIC_CLASSIFIER
RECOMMENDED`, not a fabricated deterministic label.

Any future LLM classifier must provide strict JSON Schema output containing
only the closed taxonomy, confidence, source spans, and `PSYCHOLOGY_HYPOTHESIS`
mode. It must record model provider/name/version, prompt/taxonomy version,
canonical input hash, canonical response hash, and execution timestamp.
Outputs must pass schema plus span/hash validation. Pattern promotion,
aggregation, and ranking remain deterministic over validated output. It cannot
be live-run without HG-01 external credentials.
