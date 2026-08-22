"use strict";
(function installNativeInputProbe(scope) {
  function activityButtonScreenPoint() {
    const labels = new Set(["アクティビティを見る", "View activity"]);
    const target = Array.from(document.querySelectorAll('[role="button"]'))
      .find((element) => labels.has((element.innerText || "").replace(/\s+/g, " ").trim()));
    if (!target) return null;
    const rect = target.getBoundingClientRect();
    if (!(rect.width > 0 && rect.height > 0)) return null;
    const viewport = window.visualViewport;
    const x = window.screenX + rect.x + rect.width / 2 + (viewport ? viewport.offsetLeft : 0);
    const y = window.screenY + rect.y + rect.height / 2 + (viewport ? viewport.offsetTop : 0);
    return Number.isFinite(x) && Number.isFinite(y) ? { x, y } : null;
  }
  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (!message || message.type !== "SCE_NATIVE_INPUT_SCREEN_POINT") return false;
    sendResponse({ point: activityButtonScreenPoint() });
    return false;
  });
  scope.SCE_NATIVE_INPUT_PROBE = Object.freeze({ activityButtonScreenPoint });
})(globalThis);
