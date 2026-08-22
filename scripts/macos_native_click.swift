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
      x.isFinite, y.isFinite, x >= -10000, y >= -10000, x <= 10000, y <= 10000 else {
  exit(64) // COORDINATE_OUT_OF_BOUNDS
}
guard AXIsProcessTrusted() else { exit(77) } // ACCESSIBILITY_PERMISSION_REQUIRED
let point = CGPoint(x: x, y: y)
var displayCount: UInt32 = 0
guard CGGetActiveDisplayList(0, nil, &displayCount) == .success, displayCount > 0 else { exit(65) }
var displays = Array(repeating: CGDirectDisplayID(), count: Int(displayCount))
guard CGGetActiveDisplayList(displayCount, &displays, &displayCount) == .success,
      displays.prefix(Int(displayCount)).contains(where: { CGDisplayBounds($0).contains(point) }) else {
  exit(65) // COORDINATE_OUT_OF_DISPLAY_BOUNDS
}
if moveOnly {
  guard CGWarpMouseCursorPosition(point) == .success else { exit(71) }
  guard let actual = CGEvent(source: nil)?.location,
        abs(actual.x - point.x) <= 1, abs(actual.y - point.y) <= 1 else { exit(72) }
  exit(0)
}
guard let down = CGEvent(mouseEventSource: nil, mouseType: .leftMouseDown, mouseCursorPosition: point, mouseButton: .left),
      let up = CGEvent(mouseEventSource: nil, mouseType: .leftMouseUp, mouseCursorPosition: point, mouseButton: .left) else {
  exit(70) // CGEVENT_CREATE_FAILED
}
down.post(tap: .cghidEventTap)
up.post(tap: .cghidEventTap)
exit(0) // MOUSE_DOWN_POSTED / MOUSE_UP_POSTED
