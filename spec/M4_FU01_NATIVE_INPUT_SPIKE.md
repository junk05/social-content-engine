# M4-FU01-S3 — macOS Native Input Live Spike

STATUS: `FAILED / RE-EVALUATION REQUIRED`

Contract version: `M4-FU01-NATIVE-INPUT-SPIKE-V1`

## Decision

S1 Chrome DOM/CDP input and S2 foreground CDP input both failed. S3 evaluates
one distinct mechanism only: a single macOS Quartz `CGEvent` left-click on the
screen coordinate of the already-open, dedicated worker tab's exact Activity
control.

Quartz `CGEvent` is selected over System Events/AppleScript because it is the
standard OS-level pointer-event API, needs no UI hierarchy query, and the
helper can be limited to one left down/up pair. The helper checks macOS
Accessibility trust before emitting input. It does not inspect Chrome UI.

## Fixed scope

1. Exactly one existing human-selected `DETAIL_PENDING` identity.
2. One active, focused dedicated worker tab only.
3. Extension content code reads only the exact Activity control geometry and
   viewport-to-screen coordinate metadata; it returns no page text, metric,
   credential, cookie, storage, DOM snapshot, or HTML.
4. The loopback receiver accepts one bounded, extension-origin request for that
   coordinate and invokes the fixed local helper once.
5. The helper emits only one Quartz left-down/left-up pair, then exits.
6. Existing content-side DOM confirmation observes Activity-sheet appearance
   and exact visible `view_count`; no new extraction path is introduced.
7. The worker tab closes and the run ends after the closed result.

## Security boundary

- loopback only, exact configured extension origin, one request, no retry;
- no generic coordinate endpoint: the receiver permits only the fixed S3
  request shape, one active session, and one click; it does not expose command,
  keyboard, clipboard, window, or arbitrary process controls;
- no Network/CDP Network, Cookie, Storage, DOMSnapshot, credential, search,
  scrolling, anti-detection, random timing, batch, or fallback method;
- helper source and all diagnostics are committed only as source/test fixtures;
  live coordinates, URL, source content, metrics, and permission state stay
  local and are never committed.

## Closed outcomes

`NATIVE_INPUT_SHEET_OBSERVED`, `NATIVE_INPUT_SHEET_NOT_OBSERVED`,
`ACCESSIBILITY_PERMISSION_REQUIRED`, `NATIVE_INPUT_UNAVAILABLE`,
`TARGET_NOT_FOUND`, or `NATIVE_INPUT_FAILED`.

Only `NATIVE_INPUT_SHEET_OBSERVED` plus an exact visible view count permits a
separate batch-adoption proposal. Any other result ends native click
experimentation; no further click method is authorized.

## Human boundary

HG-03 is required only to grant Accessibility control to the terminal process
running the local receiver. No login, credential, or browser setup is needed.

## HG-03 result — 2026-08-22

Closed outcome: `NATIVE_INPUT_FAILED`.

The Options UI reported that the native-input helper did not complete the
bounded action. No Activity-sheet or view-count observation was produced and
no further native click attempt is authorized by this contract.
