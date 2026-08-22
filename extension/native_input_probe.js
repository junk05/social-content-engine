"use strict";
(function installNativeInputProbe(scope) {
  function activityButtonGeometry(windowObject = window, root = document) {
    const labels = new Set(["アクティビティを見る", "View activity"]);
    const target = Array.from(root.querySelectorAll('[role="button"]'))
      .find((element) => labels.has((element.innerText || "").replace(/\s+/g, " ").trim()));
    if (!target) return null;
    const rect = target.getBoundingClientRect();
    if (!(rect.width > 0 && rect.height > 0)) return null;
    const viewport = windowObject.visualViewport;
    const viewportOffsetLeft = viewport ? viewport.offsetLeft : 0;
    const viewportOffsetTop = viewport ? viewport.offsetTop : 0;
    const viewportScale = viewport ? viewport.scale : 1;
    const frameInsetX = Math.max(0, (windowObject.outerWidth - windowObject.innerWidth) / 2);
    const browserChromeTop = Math.max(
      0, windowObject.outerHeight - windowObject.innerHeight - frameInsetX,
    );
    const centerX = rect.left + rect.width / 2;
    const centerY = rect.top + rect.height / 2;
    const screenPoint = {
      x: windowObject.screenX + frameInsetX
        + (centerX - viewportOffsetLeft) * viewportScale,
      y: windowObject.screenY + browserChromeTop
        + (centerY - viewportOffsetTop) * viewportScale,
    };
    if (![screenPoint.x, screenPoint.y].every(Number.isFinite)) return null;
    return {
      screenPoint,
      diagnostics: {
        rect: { left: rect.left, top: rect.top, width: rect.width, height: rect.height },
        centerX, centerY,
        devicePixelRatio: windowObject.devicePixelRatio,
        screenX: windowObject.screenX, screenY: windowObject.screenY,
        innerWidth: windowObject.innerWidth, innerHeight: windowObject.innerHeight,
        outerWidth: windowObject.outerWidth, outerHeight: windowObject.outerHeight,
        visualViewport: {
          offsetLeft: viewportOffsetLeft, offsetTop: viewportOffsetTop, scale: viewportScale,
        },
        frameInsetX, browserChromeTop,
      },
    };
  }
  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (!message || message.type !== "SCE_NATIVE_INPUT_SCREEN_POINT") return false;
    const geometry = activityButtonGeometry();
    sendResponse({ point: geometry ? geometry.screenPoint : null, diagnostics: geometry ? geometry.diagnostics : null });
    return false;
  });
  scope.SCE_NATIVE_INPUT_PROBE = Object.freeze({ activityButtonGeometry });
})(globalThis);
