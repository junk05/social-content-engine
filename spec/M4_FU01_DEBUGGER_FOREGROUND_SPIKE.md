# M4-FU01-S2 — Debugger Foreground Input Live Spike

STATUS: `APPROVED / IN_PROGRESS`

Contract version: `M4-FU01-DEBUGGER-FOREGROUND-SPIKE-V1`

This is the sole approved follow-up to the failed S1 debugger spike. It tests
one variable only: whether the existing CDP input sequence works when its
dedicated worker tab is foregrounded and its Chrome window is focused.

## Fixed scope

1. Select exactly one existing human-selected `DETAIL_PENDING` identity.
2. Create one dedicated worker tab for its canonical saved URL, make that tab
   active, and focus its containing Chrome window.
3. Attach `chrome.debugger` to that tab only.
4. Reuse the S1 exact Activity-control geometry evaluation and the single CDP
   `mousePressed` / `mouseReleased` pair unchanged.
5. Reuse the S1 bounded DOM confirmation unchanged.
6. Immediately detach and close the dedicated worker tab.

## Closed result and local diagnostic boundary

The only user-facing outcome is `SHEET_OBSERVED`, `TARGET_NOT_FOUND`,
`SHEET_NOT_OBSERVED_FOREGROUND`, `DEBUGGER_ATTACH_FAILED`,
`DEBUGGER_COMMAND_FAILED`, or `TAB_UNAVAILABLE`.

Immediately before the click, an ignored local in-memory audit may contain
only: canonical requested URL, current tab URL, target-tab-active boolean,
target-window-focused boolean, button rectangle, center coordinates,
debugger-attached boolean, and press/release-sent booleans. It must never be
committed, sent to the receiver, persisted, or displayed in normal extension
UI. It contains no source text, metric, credential, cookie, storage value, or
DOM content.

## Explicit prohibitions

- no CDP Network, Storage, Cookies, DOMSnapshot, screenshots, arbitrary
  Runtime evaluation, source-text extraction, or DOM persistence;
- no network retrieval beyond the existing loopback selection of one
  already-selected pending identity;
- no cookie/storage/credential access, anti-detection, random human-like
  behavior, scrolling, search, retry loop, parallel tab, batch operation, or
  queue mutation;
- no automatic fallback to any other interaction method;
- no M5 or other milestone work.

## Decision

`SHEET_OBSERVED` permits a separate evaluation of whether the foreground
method is suitable for M4-FU01 batch enrichment. Any other result ends this
line of interaction experimentation; no additional live manipulation is
authorized by this contract.

HG-03 is required for the one live execution.
