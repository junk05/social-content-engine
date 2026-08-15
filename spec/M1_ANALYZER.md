# M1 Analyzer Specification

STATUS: HUMAN-GATE APPROVED
SPEC_ID: M1-ANALYZER-V1

M1 converts normalized public-post evidence into versioned, reviewable structured analysis. It does not generate content, publish content, infer unavailable private behavior, or rewrite M0 evidence.

## 1. Goal

Build an Analyzer layer that accepts one `normalized_post` and produces a deterministic envelope containing observed text features plus model-assisted hypotheses. Every non-observed inference must be labeled as inference and tied to evidence spans from the source text.

M1 exists to answer:

`What observable content structure is present, and what bounded hypotheses can be derived from it?`

It does NOT yet answer:

`What should we post?`, `What will go viral?`, `What is the author's true psychology?`, or `What hidden engagement occurred?`

## 2. Architecture

```text
normalized_post
  -> deterministic preprocessing
  -> analyzer input contract
  -> analyzer adapter
       -> deterministic/mock analyzer for tests
       -> LLM analyzer implementation
  -> schema validation
  -> post_analysis
  -> optional pattern-instance extraction (later M1 subtask)
```

Collection and normalization remain unchanged.

## 3. Required analyzer metadata

Every analysis run MUST persist:

- `analysis_run_id`
- `source_post_id`
- `source`
- `normalized_post_version`
- `analyzer_version`
- `taxonomy_version`
- `prompt_version`
- `model_provider`
- `model_name`
- `model_parameters`
- `input_sha256`
- `output_sha256`
- `analyzed_at`
- `status`
- `error_code` when failed

Model credentials and API keys MUST NOT be persisted.

## 4. Deterministic preprocessing

Before any model call, construct an immutable Analyzer Input document containing only fields already present in the normalized post or mechanically derived from them.

Required fields:

- `source`
- `source_post_id`
- `text`
- `created_at` when observed
- `permalink` when observed
- `author_id` / observed account identifier when available
- observed public metrics already present in normalized data
- reply/root relationship identifiers when observed
- `language_hint` only if supplied by source; otherwise null

Deterministic derived text features:

- Unicode-normalized text
- character count
- line count
- URL count
- hashtag count
- mention count
- emoji count
- question-mark count
- exclamation-mark count

Do not infer sentiment, intent, psychology, topic, or quality in preprocessing.

The canonical Analyzer Input serialization MUST be deterministic and hashed with SHA-256 before the model call.

## 5. M1 taxonomy V1

`taxonomy_version = M1_TAXONOMY_V1`

The analyzer output uses four layers, following the reserved post-M0 model:

### 5.1 ACTION
What explicit or text-supported communicative action is occurring.

Allowed labels in V1:
- `ASK`
- `ASSERT`
- `SHARE_EXPERIENCE`
- `ADVISE`
- `INVITE_RESPONSE`
- `EXPRESS_EMOTION`
- `EXPLAIN`
- `COMPARE`
- `ANNOUNCE`
- `OTHER`

Multiple labels allowed.

### 5.2 PSYCHOLOGY_HYPOTHESIS
Bounded hypotheses about the psychological frame expressed by the text, not the author's hidden or clinical state.

Allowed labels in V1:
- `SEEKING_VALIDATION`
- `SEEKING_CONNECTION`
- `UNCERTAINTY`
- `CONFLICT`
- `SELF_REFLECTION`
- `HOPE`
- `FRUSTRATION`
- `FEAR_OR_ANXIETY_EXPRESSED`
- `DESIRE_OR_LONGING`
- `BOUNDARY_SETTING`
- `OTHER`

Every psychology item MUST be marked `inference=true` and MUST contain source evidence spans.

The engine MUST NOT diagnose mental illness, personality disorders, attachment style, trauma, deception, infidelity, or other hidden traits from a post.

### 5.3 STRUCTURE
Observable rhetorical/content structure.

Allowed labels in V1:
- `HOOK_FIRST`
- `QUESTION_LED`
- `STORY_ARC`
- `PROBLEM_SOLUTION`
- `LIST_OR_ENUMERATION`
- `CONTRAST`
- `CALL_TO_ACTION`
- `OPEN_LOOP`
- `SHORT_PUNCHY`
- `LONG_FORM`
- `OTHER`

### 5.4 CONTENT
Broad content subject, expressed as normalized tags rather than an unrestricted essay.

Required fields:
- `primary_topic`
- `secondary_topics[]`
- `entities[]` only when explicitly present
- `keywords[]`

Topic vocabulary is open in M1, but tags MUST be concise, lower-level descriptions of the actual text and MUST NOT invent events or relationships not stated in the source.

## 6. Evidence contract

Every ACTION, PSYCHOLOGY_HYPOTHESIS and STRUCTURE item MUST contain:

- `label`
- `confidence`
- `evidence[]`

Each evidence item:

```json
{
  "quote": "exact substring from source text",
  "start": 0,
  "end": 12
}
```

`start` is inclusive and `end` is exclusive over the canonical Unicode-normalized Analyzer Input text.

The quoted text MUST exactly equal `text[start:end]`.

If no valid evidence span exists, the label MUST NOT be emitted.

## 7. Confidence

Confidence is a bounded evidence-confidence value, not truth probability.

Allowed values:
- `HIGH`
- `MEDIUM`
- `LOW`

Rules:
- direct linguistic evidence may be HIGH;
- interpretation requiring context not present in the post cannot be HIGH;
- weak psychology hypotheses should be LOW or omitted;
- unsupported labels are forbidden.

## 8. Output contract

Conceptual output:

```json
{
  "schema_version": 1,
  "analysis_run_id": "...",
  "source_post_id": "...",
  "taxonomy_version": "M1_TAXONOMY_V1",
  "analyzer_version": "...",
  "prompt_version": "...",
  "model": {
    "provider": "...",
    "name": "...",
    "parameters": {}
  },
  "input_sha256": "...",
  "actions": [],
  "psychology_hypotheses": [],
  "structures": [],
  "content": {
    "primary_topic": "...",
    "secondary_topics": [],
    "entities": [],
    "keywords": []
  },
  "warnings": [],
  "analyzed_at": "..."
}
```

A JSON Schema under `spec/contracts/` MUST enforce this contract.

## 9. Storage

Activate the reserved post-M0 tables:

### `analysis_runs`
One row per analyzer execution attempt, including version/model/input hash/status/error provenance.

### `post_analysis`
Validated structured output linked to exactly one `analysis_run` and one normalized source post.

M1 MUST NOT overwrite prior analyses. Re-analysis creates a new run/output so analyzer versions remain comparable.

## 10. Analyzer adapter

Define an interface separating orchestration from model provider.

Required behavior:
- accept canonical Analyzer Input
- return candidate JSON only
- no direct DB writes from provider adapter
- caller validates schema/evidence before persistence

Tests MUST use a deterministic fake/mock adapter and MUST NOT require a paid external model call.

The first real LLM adapter may use an environment-provided credential, but implementation MUST keep provider-specific code behind the interface.

## 11. Validation and rejection

Before persistence, reject output if any of the following occur:

- invalid JSON/schema
- unknown closed-taxonomy label
- confidence outside allowed enum
- evidence quote does not match source substring
- span outside source bounds
- psychology hypothesis without `inference=true`
- missing version metadata
- content invents unavailable source facts detectable by evidence validation

Rejected attempts remain recorded in `analysis_runs` with status/error; invalid `post_analysis` is not persisted.

## 12. Idempotency and replay

Identical `(source_post_id, analyzer_version, taxonomy_version, prompt_version, model_name, model_parameters, input_sha256)` MAY be reused instead of creating duplicate successful analyses when explicitly requested by orchestration.

Default CLI behavior in M1 should support:
- `--force` to create a fresh analysis run
- otherwise reuse an identical prior successful analysis when available

Raw/normalized M0 evidence is never modified by Analyzer execution.

## 13. M1 CLI

Provide a minimal analyzer command capable of analyzing a normalized fixture/post by ID.

Expected conceptual forms:

```text
sce-analyze --post-id <id>
sce-analyze --post-id <id> --force
```

A deterministic fixture/mock mode MUST be available for CI without external credentials.

## 14. Golden Cases

M1 test suite MUST contain sanitized representative posts and freeze expected structural behavior.

At minimum:
- question-led post
- explicit personal experience
- advice/problem-solution post
- emotional expression with bounded psychology hypothesis
- ambiguous post where psychology is omitted/LOW
- post with URL/hashtags/mentions/emoji
- Japanese text with evidence-span verification
- empty/minimal text edge case
- malformed analyzer output rejection
- replay/idempotency case

Golden Cases MUST validate schema, evidence spans, deterministic preprocessing and persistence behavior. They MUST NOT freeze one commercial LLM's exact prose.

## 15. Security and privacy

- Analyze only data already permitted and collected by M0.
- Do not enrich public posts with private or purchased personal data.
- Do not infer sensitive personal attributes unless explicitly stated and necessary; M1 taxonomy does not require them.
- Never persist model API keys.
- Do not send raw credential/provenance secrets to model providers.
- Sanitized fixtures only in Git.

## 16. Explicitly deferred

Not part of M1 Analyzer V1:
- ranking posts by virality
- engagement prediction
- automatic pattern mining across many posts
- creator profiling
- content generation
- automatic publishing
- Fortune Engine integration
- dashboards
- autonomous posting strategy

Those require later approved specs.

## 17. Definition of Done

M1 Analyzer V1 is complete when:

1. Analyzer Input contract/preprocessor implemented.
2. Analyzer Output JSON Schema implemented.
3. `analysis_runs` and `post_analysis` persistence implemented.
4. deterministic mock adapter implemented.
5. real-model adapter boundary implemented without requiring live credential in CI.
6. evidence-span validator implemented.
7. CLI implemented.
8. Golden Cases pass.
9. existing M0 tests remain green.
10. CI passes on supported Python versions.
11. no credentials/live raw data are committed.
12. SSOT marks M1 COMPLETE only after all above are verified.
