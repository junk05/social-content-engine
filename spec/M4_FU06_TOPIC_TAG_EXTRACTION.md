# M4-FU06 — Topic Tag Extraction Repair

STATUS: `IN_PROGRESS / HG-03 PENDING`

Change record: `CR-0023`.

## Contract

Detail extractor v7 identifies the canonical post content container before
selecting author text. Topic links/labels, timestamps, profile labels, metrics,
sequence indicators, buttons, and navigation labels are not body candidates.
Observed topic labels are stored separately as `topic_tags[]` with ordinary
field provenance. A one-word body remains valid when its DOM node is content,
even when it equals a topic label.

Root and self-reply details share this extractor. Topic metadata remains
ANALYSIS_ONLY_SOURCE and is not copied into structural components or a
Generation-facing DTO.

Legacy suspected values may be explicitly requeued without changing quality.
After reobservation, an old detail observation is confirmed as
`INVALID_TEXT_TOPIC_TAG_METADATA` only when v7 observes that exact old value as
a topic tag for the same post and observes a different body (or no body).
Assessments are append-only; source observations are never changed or deleted.

Human Review CSV includes `topic_tags` and `topic_tag_count` for roots and
Thread nodes.

## Definition of Done

1. body plus tag, tag-only, tag-free, and genuine one-word body fixtures pass;
2. roots and self replies use the same v7 separation;
3. topic metadata and provenance survive normalization and duplicate-safe storage;
4. confirmed legacy defects are excluded from clean analysis without deletion;
5. named legacy candidates can be requeued without being declared invalid;
6. both review CSVs expose separated topic metadata;
7. all M0-M4/M4-FU01 regression and repository validation pass;
8. known topic-tagged live posts pass HG-03; M5 remains unauthorized.
