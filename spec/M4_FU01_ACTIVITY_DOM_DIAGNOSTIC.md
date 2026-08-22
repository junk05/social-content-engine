# M4-FU01-S5 — Activity Sheet DOM Diagnostic

STATUS: `IMPLEMENTED / HG-03 LIVE SPIKE REQUIRED`

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
