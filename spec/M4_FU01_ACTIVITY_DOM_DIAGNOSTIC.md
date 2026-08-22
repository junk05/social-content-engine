# M4-FU01-S5 — Activity Sheet DOM Diagnostic

STATUS: `ROOT_CAUSE_CONFIRMED / RE-EVALUATION REQUIRED`

Contract version: `M4-FU01-ACTIVITY-DOM-DIAGNOSTIC-V1`

## Goal

Keep the proven, calibrated Quartz click unchanged. After its Activity sheet
opens on one selected post, diagnose the visible DOM read-only, extract the
exact view count, ingest the existing `POST_DETAIL` observation through the
loopback receiver, and verify `DETAIL_ENRICHED`.

## Diagnostic boundary

The local ephemeral result may contain counts, tag names, fixed accessibility
roles, visibility states, sanitized Activity labels, structural depth, and the
observed exact view count. It must not persist or commit post text, URL,
username, author, arbitrary DOM text, DOM dumps, cookies, storage, network
traffic, credentials, selectors based on generated classes, or shadow content.

The probe checks visible dialog/modal candidates, exact Activity label nodes,
same-node and split label/value structures, bounded parents and siblings,
open-shadow-root and iframe counts, and bounded render timing. It supports both
`閲覧数\n<integer>` and label/value sibling forms. Locale terms remain in one
closed matcher.

## Live result

PASS requires one existing Quartz click, visible Activity sheet, exact
`view_count`, accepted `POST_DETAIL`, and receiver state `DETAIL_ENRICHED`.
FAIL records a closed structural reason without adopting a new input method.
No batch operation or M5 work is authorized before PASS.

## Live diagnostic record

- Attempt 1: Quartz click and visible modal dialog succeeded. The dialog was
  neither iframe nor open shadow-root content, but no current exact/split Views
  label matched. A human-provided DOM location showed metric values nested in
  `span/span`. The next read-only diagnostic is limited to canonical metric
  kinds, exact numeric leaf values, and dialog-relative tag/index paths; it
  emits no arbitrary text, IDs, classes, post fields, or URLs.
- Attempt 2: the visible dialog exposed structurally paired Likes, Reposts,
  Quotes, and exact integer leaves, proving that visibility and traversal work.
  No Views kind was classified. The next diagnostic adds the localized
  `ビュー` label and numeric-only rounded-shape reporting. Rounded values remain
  unavailable and are never converted into an exact view count.
- Attempt 3: the expanded locale and numeric-shape probe again found a visible
  modal with structurally paired Likes, Reposts, Quotes, and their exact
  integer leaves. It found no Views label, no exact Views value, and no rounded
  numeric leaf inside the sheet. The provided DOM location corroborated the
  Likes value structure. Root cause: this selected public post's Activity sheet
  does not render a view-count field. This is observed metric unavailability,
  not a Quartz click, visibility, timing, iframe, shadow-root, normalizer, or
  label/value traversal failure. Missing views remain unavailable; rounded page
  headers are not converted to exact counts.

The calibrated Quartz path remains technically viable for opening Activity and
reading metrics that are actually rendered. Batch adoption and the M4-FU01 DoD
remain pending a separate re-evaluation of nullable-view detail enrichment or
a selected post where exact Views evidence is observably present. This result
does not close native input and does not authorize another interaction method.
