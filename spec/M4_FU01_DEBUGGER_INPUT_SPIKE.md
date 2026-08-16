# M4-FU01-S1 — Debugger Input Live Spike

STATUS: `APPROVED / IN_PROGRESS`

Contract version: `M4-FU01-DEBUGGER-INPUT-SPIKE-V1`

This is a bounded revision to M4-FU01. It does not authorize the complete
automated detail-enrichment batch, M5, content generation, or any broad browser
automation.

## Purpose

Establish only whether a Chrome `debugger` session, restricted to one dedicated
detail tab for one already human-selected `DETAIL_PENDING` post, can open the
visible Threads `アクティビティを見る` sheet using CDP Input mouse events.

The preceding content-script `element.click()` spike did not produce the sheet
in live Threads UI. The exact button and manual sheet evidence are known, but
the cause remains `UNKNOWN` until this spike records PASS or FAIL.

## Fixed scope

1. The user has already selected the post through `Pattern収集`.
2. The extension creates or reuses one inactive dedicated detail tab for that
   canonical saved URL.
3. It attaches `chrome.debugger` to that tab only.
4. It uses a bounded `Runtime.evaluate` expression only to find the exact,
   visible `DIV[role=button]` labelled `アクティビティを見る` (or the documented
   English equivalent) and return its viewport-center coordinates. No page
   text, URL list, credentials, cookies, storage values, DOM snapshots, HTML,
   or network data may be read or returned.
5. It sends exactly `Input.dispatchMouseEvent` `mousePressed` then
   `mouseReleased` at those coordinates.
6. Existing content-script code observes only whether a new visible sheet with
   the exact public `閲覧数`/`表示` integer metric appears.
7. It records only a closed success/failure result and immediately detaches.

## Explicit prohibitions

- no `Network`, `Storage`, `Cookies`, `DOMSnapshot`, `Page.captureScreenshot`,
  `Runtime.evaluate` source-text extraction, or arbitrary evaluation;
- no search, scrolling, selection, retry loop, parallel tab, normal user-tab
  navigation, anti-detection, or credential extraction;
- no metrics or detail observation persistence during this spike;
- no change to `DETAIL_PENDING` queue state;
- no integration into the detail batch controller.

## Closed outcomes

- `SHEET_OBSERVED`: exact sheet appears after press/release;
- `TARGET_NOT_FOUND`: exact visible button cannot be located;
- `SHEET_NOT_OBSERVED`: target was dispatched but no sheet appears before the
  bounded timeout;
- `DEBUGGER_ATTACH_FAILED`, `DEBUGGER_COMMAND_FAILED`, or `TAB_UNAVAILABLE`.

Results contain no source text, URL, user identity, coordinates, or browser
data. The live result is a local, ignored audit record only.

## Human boundary and Definition of Done

`debugger` is a material extension permission and is approved only for this
spike. HG-03 is required before using it against the signed-in Threads page.

The spike passes only if one human-selected pending post produces
`SHEET_OBSERVED`, followed by immediate detach. A PASS authorizes a separate
approved implementation task for batch integration; it does not itself change
the M4-FU01 batch contract. A FAIL records the closed outcome and requires
re-evaluation before additional automation.
