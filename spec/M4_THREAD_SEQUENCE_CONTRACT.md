# M4 Thread Sequence Contract

STATUS: APPROVED

Short posts are not a missing-data class. Each observed root or reply is
classified independently as `STANDALONE_SHORT`, `OPEN_LOOP_SHORT`,
`PARENT_TO_SELF_REPLY`, or `LONG_FORM`. The classification is a closed,
evidence-backed hypothesis; no relationship is inferred from wording alone.

For M4 V2, short form means text of at most 100 Unicode code points. A short
post with a span-backed internal information gap is `OPEN_LOOP_SHORT`; one
without that mechanism is `STANDALONE_SHORT`. Any root with an observed
same-author reply edge is `PARENT_TO_SELF_REPLY` regardless of its length.
`LONG_FORM` otherwise requires more than 100 code points. An absent edge is
`UNKNOWN`, never evidence against a self-reply pattern.

Thread structure is an observed directed graph, not a parent-to-one-reply
model. Every observed node stores `root_post_id`, `sequence_position`,
`reply_to_post_id`, and `same_author_as_root` only when those values are visible
in the already-open detail surface. Missing values remain `UNKNOWN`.

Self-reply membership additionally requires versioned relationship evidence that
the node belongs to the root-author-owned conversation branch. Traversal starts
at the root and may continue through consecutive root-author nodes. Once the
visible conversation order enters another author, that branch is closed: a
later root-author reply is not allowed to rejoin the Pattern Thread Sequence.
Username equality, page co-presence, and timestamp proximity are insufficient.

M4 may aggregate only eligible observed chains such as `Root -> Self Reply 1 -> Self
Reply 2`. It derives the abstract sequence `Hook -> Open Loop -> Self Reply
Transition -> Explanation/Escalation -> Payoff -> CTA` only when each relevant
edge and node evidence exists. Original wording, URLs, and usernames remain
forbidden in Pattern storage.

M3 detail extraction owns the one shared visible-DOM observation path. Future
automated detail enrichment must reuse this contract and extractor; it must not
create a parallel DOM parser. Human-selected collection remains required until
an explicitly approved future milestone changes that boundary.
