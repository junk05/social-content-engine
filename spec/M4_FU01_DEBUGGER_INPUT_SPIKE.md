# M4-FU01-S1 — Debugger Input Live Spike

STATUS: `FAILED / RE-EVALUATION REQUIRED`

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

- no CDP `Network`, `Storage`, `Cookies`, `DOMSnapshot`, `Page.captureScreenshot`,
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
data. The extension displays only the closed outcome; the HG-03 result is
recorded in the SSOT after the human observes it.

## Human boundary and Definition of Done

`debugger` is a material extension permission and is approved only for this
spike. HG-03 is required before using it against the signed-in Threads page.

The spike passes only if one human-selected pending post produces
`SHEET_OBSERVED`, followed by immediate detach. A PASS authorizes a separate
approved implementation task for batch integration; it does not itself change
the M4-FU01 batch contract. A FAIL records the closed outcome and requires
re-evaluation before additional automation.

## HG-03 result — 2026-08-22

Closed outcome: `SHEET_NOT_OBSERVED`.

The extension selected exactly one existing `DETAIL_PENDING` identity and
completed the bounded command path without an attach, target, or command
failure. The post-dispatch content-side confirmation did not observe the
Activity sheet within its bounded timeout. No metric, source content, URL,
identity, browser data, or queue state was persisted.

The exact cause is `UNKNOWN`. The remaining candidates include an interaction
requirement of the inactive tab, an unobserved UI timing/state requirement, or
a narrow sheet-detector mismatch. This contract forbids another live attempt
or a broader debugger action. Any follow-up must be separately approved.
