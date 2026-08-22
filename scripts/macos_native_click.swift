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
guard values.count == 2,
      let x = Double(values[values.startIndex]), let y = Double(values[values.index(after: values.startIndex)]),
      x.isFinite, y.isFinite, x >= 0, y >= 0, x <= 10000, y <= 10000 else {
  exit(64)
}
guard AXIsProcessTrusted() else { exit(77) }
let point = CGPoint(x: x, y: y)
guard let down = CGEvent(mouseEventSource: nil, mouseType: .leftMouseDown, mouseCursorPosition: point, mouseButton: .left),
      let up = CGEvent(mouseEventSource: nil, mouseType: .leftMouseUp, mouseCursorPosition: point, mouseButton: .left) else {
  exit(70)
}
down.post(tap: .cghidEventTap)
up.post(tap: .cghidEventTap)
exit(0)
