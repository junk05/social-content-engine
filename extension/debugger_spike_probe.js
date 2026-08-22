"use strict";

// Content-side confirmation only. This performs no debugger/CDP operation and
// exposes no DOM text, metrics, URL, storage, cookies, or page data.
(function installDebuggerSpikeProbe(scope) {
  function isVisible(element) {
    return element && !element.hidden && element.getAttribute("aria-hidden") !== "true";
  }

  function exactActivityMetricPresent() {
    return Array.from(document.querySelectorAll("span, div")).some((element) => {
      const text = (element.innerText || "").replace(/\s+/g, " ").trim();
      return isVisible(element) && /^(?:閲覧数|views?)\s*[:：]?\s*[0-9][0-9,]*\s*(?:回|views?)?$/i.test(text);
    });
  }

  function waitForActivitySurface(timeout = 4000) {
    return new Promise((resolve) => {
      if (exactActivityMetricPresent()) { resolve(true); return; }
      const observer = new MutationObserver(() => {
        if (exactActivityMetricPresent()) { observer.disconnect(); clearTimeout(timer); resolve(true); }
      });
      observer.observe(document.documentElement, { childList: true, subtree: true });
      const timer = setTimeout(() => { observer.disconnect(); resolve(false); }, timeout);
    });
  }

  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (!message || message.type !== "SCE_DEBUGGER_SPIKE_CONFIRM_ACTIVITY") return false;
    waitForActivitySurface().then((activitySurface) => sendResponse({ activitySurface }));
    return true;
  });

  scope.SCE_DEBUGGER_SPIKE_PROBE = Object.freeze({ exactActivityMetricPresent, waitForActivitySurface });
})(globalThis);
