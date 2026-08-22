"use strict";
(function installNativeInputProbe(scope) {
  function activityButtonScreenPoint() {
    const labels = new Set(["アクティビティを見る", "View activity"]);
    const target = Array.from(document.querySelectorAll('[role="button"]'))
      .find((element) => labels.has((element.innerText || "").replace(/\s+/g, " ").trim()));
    if (!target) return null;
    const rect = target.getBoundingClientRect();
    if (!(rect.width > 0 && rect.height > 0)) return null;
    const chromeTop = Math.max(0, window.outerHeight - window.innerHeight);
    const x = window.screenX + rect.x + rect.width / 2;
    const y = window.screenY + chromeTop + rect.y + rect.height / 2;
    return Number.isFinite(x) && Number.isFinite(y) ? { x, y } : null;
  }
  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (!message || message.type !== "SCE_NATIVE_INPUT_SCREEN_POINT") return false;
    sendResponse({ point: activityButtonScreenPoint() });
    return false;
  });
  scope.SCE_NATIVE_INPUT_PROBE = Object.freeze({ activityButtonScreenPoint });
})(globalThis);
