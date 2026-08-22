"use strict";
(function exposeNativeCoordinate(scope) {
  function calibratedScreenPoint(geometry, windowBounds) {
    const diagnostics = geometry && geometry.diagnostics;
    const original = geometry && geometry.point;
    if (!diagnostics || !original || !windowBounds) return null;
    const values = [
      original.x,
      diagnostics.centerY,
      diagnostics.innerHeight,
      diagnostics.visualViewport.offsetTop,
      diagnostics.visualViewport.scale,
      windowBounds.top,
      windowBounds.height,
    ];
    if (!values.every(Number.isFinite)) return null;
    const contentOriginY = windowBounds.top + windowBounds.height - diagnostics.innerHeight;
    const y = contentOriginY
      + (diagnostics.centerY - diagnostics.visualViewport.offsetTop)
        * diagnostics.visualViewport.scale;
    return Number.isFinite(y) ? { x: original.x, y } : null;
  }

  scope.SCE_NATIVE_COORDINATE = Object.freeze({ calibratedScreenPoint });
})(globalThis);
