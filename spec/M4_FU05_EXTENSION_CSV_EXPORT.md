# M4-FU05 — Extension Human Review CSV Downloads

STATUS: `COMPLETE`

Change record: `CR-0022`.

## Goal

Let a human download the existing M4-FU02 canonical-root and Thread Sequence
review CSVs from Extension options without adding a second CSV implementation.

## Contract

The exact-origin loopback endpoint renders either `threads_posts.csv` or
`threads_thread_nodes.csv` through the existing read-only row builders and
shared UTF-8 BOM serializer. The selected collected-root status filter is one
of `ALL`, `DETAIL_PENDING`, `DETAIL_FAILED`, `DETAIL_ENRICHED`, or `EXCLUDED`.

The endpoint accepts only `GET`, a closed export kind, a closed filter, a
loopback listener, and the configured exact Extension origin. The Extension
downloads the returned Blob locally. CSV generation never runs in Extension
code, does not mutate SQLite, and does not write server-side live files.

Source text and identities remain `ANALYSIS_ONLY_SOURCE` for Human Review.
They are not Generation-facing and no generated CSV is committed.

## Definition of Done

1. both review CSV kinds reuse M4-FU02 row builders and serialization;
2. Options provides `投稿一覧CSV` and `Thread Sequence CSV` controls;
3. the currently selected status filter is applied to both exports;
4. UTF-8 BOM, Japanese text, URLs, null/zero, and Thread rows remain intact;
5. export is read-only, exact-origin-only, and rejects unknown inputs;
6. existing exporter, receiver, Extension, and full repository regressions pass;
7. one atomic commit is pushed to `main`; M5 remains unauthorized.
