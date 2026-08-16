# M4 Structural Pattern Extraction

STATUS: `APPROVED REVISION UNDER CR-0006`

M4 prioritizes deterministic, genre-independent Structural Pattern Extraction.
LLM semantic/psychology classification is an optional future enrichment layer.
M4 remains `IN_PROGRESS`; M5 remains prohibited.

## Layer boundaries

### Analysis-only source

Existing raw/browser observations, normalized versions, source text, canonical
URLs, author identity, timestamps, observed metrics, relationship evidence,
extractor versions, and provenance are the Source Layer. They remain available
for collection, audit, and future reanalysis only.

### Structural feature layer

One immutable structural feature instance is derived from a pinned normalized
post version. It contains only closed component IDs, ordered component spans
and hashes, feature/taxonomy/extractor versions, and canonical input/output
hashes. It must not retain source text, URL, author identity, quote text, or
free-form interpretation.

The initial closed component vocabulary is:

`QUESTION`, `ASSERTION`, `NEGATION`, `NUMBER`, `LIST_PREVIEW`,
`TARGET_READER`, `DIRECT_ADDRESS`, `EXPERIENCE_STATEMENT`,
`TIME_OR_AGE_REFERENCE`, `COMPARISON`, `CONTRAST`, `CONDITION`,
`PROBLEM_STATEMENT`, `RESULT_STATEMENT`, `REASON_PREVIEW`,
`CONCLUSION_PREVIEW`, `SECRET_REVEAL`, `INCOMPLETE_INFORMATION`,
`CONCRETE_SCENE`, `EMOTIONAL_EXPRESSION`, `ADVICE_OR_COMMAND`, `QUOTE`,
`TRANSITION`, and `CTA`.

Every component needs deterministic span/hash evidence. A missing component is
absent, not inferred. Domain labels are forbidden.

### Local and post/thread patterns

A Local Pattern is an abstract, text-free formula over ordered component IDs.
Only two or more distinct source posts promote a reusable Pattern. A Post
Structure is the ordered component sequence over the normalized post. Thread
Structure consumes only observed sequence edges and never infers a self-reply.

## Generation isolation

`ANALYSIS_ONLY_SOURCE` is unavailable to Generation. A future generator can
receive only `GENERATION_SAFE_PATTERN`: abstract formula, component IDs and
sequence, aggregate support/performance statistics, confidence, and
taxonomy/analyzer versions. It must not receive source text, URLs, authors,
source identifiers, excerpts, embeddings, or source-retrieval handles.

This is an interface boundary: the generation-safe DTO accepts no Repository,
source-reference, or source-text fields, and generation package tests forbid
imports from source storage. Analysis/audit code may retain source evidence
references internally.

## HG-04 report requirements

The revised local Structural Pattern Report must contain aggregate-only Top
First-Line Component Patterns, Post Structure Patterns, observed Thread
Structure Patterns (or explicit insufficient evidence), support/evidence
counts, confidence, metrics coverage, versions, and a source-text-free
generation-safe view. It must not claim psychological causality or expose
source wording/identity.
