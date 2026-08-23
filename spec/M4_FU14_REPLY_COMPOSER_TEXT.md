# M4-FU14 — Reply Composer Text Exclusion

STATUS: `IN_PROGRESS`

Change record: `CR-0031`.

## Root cause

The detail extractor fallback considered every visible `[dir="auto"]` node in
the bounded post card. The reply composer placeholder is also rendered on that
surface with `dir="auto"`; when the real body was absent from the fallback set
or shorter, the longest-candidate rule promoted the composer text to `text`.

## Contract

Extractor v17 excludes candidates inside semantic input/composer surfaces:
`textarea`, `input`, `role=textbox`, `contenteditable=true`, and explicit
placeholder-bearing ancestors. Wording alone is not an exclusion rule, so an
author can still publish text containing the word `返信`.

Confirmed historical observations receive append-only
`INVALID_TEXT_REPLY_COMPOSER_METADATA` quality evidence. They are never edited
or deleted and affected canonical roots are explicitly requeued for current
detail observation. Human Review selection must not prefer the invalid evidence
over a newer non-invalid detail observation. M5 remains unauthorized.

## Definition of Done

1. a composer placeholder cannot displace a genuine short body;
2. genuine authored reply wording remains eligible outside composer DOM;
3. the new quality status migrates append-only and is excluded from clean data;
4. affected roots are identified without exposing source content in Git;
5. affected roots can be re-enriched without deleting observations;
6. CSV no longer selects confirmed composer metadata after reobservation;
7. full regression, repository validation, and CI pass.

## Local audit

Five canonical roots selected an identical reply-composer placeholder from
extractor v14. All five immutable observations now have append-only confirmed
invalid quality evidence and all five roots are `DETAIL_PENDING` for an
extractor-v17 reobservation. Aggregate, source-free evidence is recorded in
`spec/evidence/M4_FU14_REPLY_COMPOSER_AUDIT.json`. HG-03 live reobservation and
CSV verification remain pending.
