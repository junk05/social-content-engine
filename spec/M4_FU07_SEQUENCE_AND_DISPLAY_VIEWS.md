# M4-FU07 — Sequence Indicator and Display Views

STATUS: `IN_PROGRESS`

Change record: `CR-0024`.

## Sequence indicator

Inside the canonical post content region, `div.x1rg5ohu` is a current DOM hint,
not a permanent contract. A candidate is metadata only when the hint (or a
semantic sequence attribute) and strict `N / total` form both match. The
extractor stores `raw_sequence_indicator`, `thread_position`, and
`thread_total`, and removes only that observed UI token from body text. Matching
author text without DOM evidence is preserved.

## Display Views

Detail-page Views retain the raw display and deterministic normalization:

- integer displays such as `表示4,506回` use `precision=DISPLAY_EXACT` and
  `normalized_value=4506`;
- magnitude displays such as `表示1.2万回` use `precision=ROUNDED` and retain
  the existing approximate normalization;
- missing and malformed displays remain unavailable, never zero.

Both forms remain Source evidence with observed time, extractor, normalizer,
surface, and view band. Rounded observations are descriptive only. M5 remains
unauthorized.

## Definition of Done

1. DOM-confirmed sequence UI is separated for roots and self replies;
2. author-written fraction text is preserved without DOM evidence;
3. 4506, 999, 1.2万, 10万, missing, and malformed Views fixtures pass;
4. exact-display and rounded precision remain distinct in storage and CSV;
5. full regressions and CI pass;
6. HG-03 verifies current DOM behavior without committing live content.
