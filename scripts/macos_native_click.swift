import ApplicationServices
import Foundation

// One-shot local helper for M4-FU01-S3. It accepts exactly two finite screen
// coordinates and emits exactly one left-down / left-up pair; no keyboard,
// clipboard, application inspection, or network capability exists here.
let values = CommandLine.arguments.dropFirst()
if values.count == 1 && values[values.startIndex] == "--diagnose" {
  // Non-input probe: this must never create or post an event.
  exit(AXIsProcessTrusted() ? 0 : 77)
}
let moveOnly = values.count == 3 && values[values.startIndex] == "--move"
let numeric = moveOnly ? values.dropFirst() : values
guard numeric.count == 2,
      let x = Double(numeric[numeric.startIndex]), let y = Double(numeric[numeric.index(after: numeric.startIndex)]),
      x.isFinite, y.isFinite, x >= 0, y >= 0, x <= 10000, y <= 10000 else {
  exit(64) // COORDINATE_OUT_OF_BOUNDS
}
guard AXIsProcessTrusted() else { exit(77) } // ACCESSIBILITY_PERMISSION_REQUIRED
let point = CGPoint(x: x, y: y)
if moveOnly { CGWarpMouseCursorPosition(point); exit(0) }
guard let down = CGEvent(mouseEventSource: nil, mouseType: .leftMouseDown, mouseCursorPosition: point, mouseButton: .left),
      let up = CGEvent(mouseEventSource: nil, mouseType: .leftMouseUp, mouseCursorPosition: point, mouseButton: .left) else {
  exit(70) // CGEVENT_CREATE_FAILED
}
down.post(tap: .cghidEventTap)
up.post(tap: .cghidEventTap)
exit(0) // MOUSE_DOWN_POSTED / MOUSE_UP_POSTED
