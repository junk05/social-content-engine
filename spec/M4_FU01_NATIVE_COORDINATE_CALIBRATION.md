# M4-FU01-S4 — Native Coordinate Calibration

STATUS: `IMPLEMENTED / HG-03 CURSOR ALIGNMENT REQUIRED`

Contract version: `M4-FU01-NATIVE-COORDINATE-CALIBRATION-V1`

## Purpose

The S3 Quartz event path moved the macOS cursor, but the pointer missed the
exact Activity control. S4 keeps the same Quartz mechanism and changes only
the deterministic DOM-viewport to macOS-screen coordinate conversion.

## Fixed stages

1. `CURSOR_TARGET_ALIGNMENT`: one selected `DETAIL_PENDING` post, one active
   dedicated worker tab, one move-only Quartz cursor warp, and no click.
2. HG-03 visual confirmation that the pointer is centered on the exact
   `アクティビティを見る` control.
3. Only after `CURSOR_TARGET_ALIGNED`, reuse the same conversion and existing
   Quartz left-down/left-up pair exactly once.

## Coordinate contract

The content probe may read only the Activity control's bounding rectangle,
center, `devicePixelRatio`, `screenX/Y`, inner/outer dimensions, and
`visualViewport` offset/scale. It derives browser-chrome offsets explicitly.
DOM viewport coordinates are never passed directly to Quartz. JavaScript
screen coordinates are already logical screen points; `devicePixelRatio` is
recorded but is not multiplied into the Quartz point.

The helper validates the point against the union of active macOS display
bounds, performs either one move-only operation or the existing one click,
and returns only closed status codes. Live coordinates and browser geometry
remain local and are not committed.

## Prohibitions

- no random movement, retry loop, scrolling, search, keyboard, clipboard,
  cookie/storage/credential access, anti-detection, or alternate input method;
- no click during Stage 1;
- no batch operation or M5 work;
- no Stage 2 click before explicit HG-03 alignment confirmation.

## Closed outcomes

Stage 1: `CURSOR_MOVE_SENT`, `CURSOR_TARGET_ALIGNED` (human),
`CURSOR_TARGET_MISALIGNED`, `COORDINATE_OUT_OF_BOUNDS`, or helper failure.

Stage 2: `NATIVE_INPUT_SHEET_OBSERVED` only when the Activity sheet and exact
view count are both observed; otherwise `NATIVE_INPUT_SHEET_NOT_OBSERVED` or a
closed helper error. Any Stage 2 failure ends native-input experimentation.

## Live calibration record

- 2026-08-22 Stage 1 attempt 1: `CURSOR_TARGET_MISALIGNED`. The cursor moved
  into the post body above the Activity control. No click was sent. A text-free
  ephemeral geometry readout is required before changing the deterministic
  conversion.
- The text-free diagnostics showed that Brave's JavaScript `screenY` omitted
  the browser UI inset while the extension window bounds exposed it. The next
  move-only attempt therefore derives the vertical content origin from window
  top plus window height minus inner viewport height. Horizontal conversion
  remains unchanged because no horizontal miss was observed.
- 2026-08-22 Stage 1 attempt 2: `CURSOR_TARGET_ALIGNED`. Human visual review
  confirmed that the move-only pointer reached the center of the Activity
  control. Stage 2 is now authorized to reuse this exact conversion for one
  existing Quartz click.
- 2026-08-22 Stage 2 attempt 1: the existing Quartz click opened the Activity
  sheet (`NATIVE_INPUT_SHEET_VISUALLY_OBSERVED`), but the confirmation probe
  returned `NATIVE_INPUT_SHEET_NOT_OBSERVED` and captured no exact view count.
  No further click was sent. The probe must accept the already-supported exact
  `表示 <integer> 回` label variant and use the same bounded eight-second DOM
  wait as detail enrichment before any separately gated confirmation run.
