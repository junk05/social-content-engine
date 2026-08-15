# Milestones

## M0 — Real Threads data capture

Status: `IN_PROGRESS`

Definition of Done:

1. Threads API capability matrix is evidence-backed.
2. Authentication method is determined.
3. At least one real public post is obtained through an official permitted API.
4. The unmodified raw response is stored.
5. A normalized post is derived.
6. Provenance is stored.
7. Recollection does not create a duplicate normalized post.
8. A sanitized fixture exists.
9. Automated tests pass.
10. CI passes.

The pipeline for items 4–7 is verified with a synthetic fixture. Satisfying those
items with real data, beginning with item 3, requires a live credential and is
tracked by HG-01 until configured.

## Deferred until M0 completion

- analyzers and pattern mining
- content generation and automatic publishing
- Fortune Engine integration
- dashboards, production deployment, and large-scale infrastructure
