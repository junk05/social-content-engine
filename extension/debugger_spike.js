"use strict";

// Narrow, auditable capability spike.  Do not add CDP domains here: the only
// browser-protocol commands permitted are Runtime.evaluate for one bounding
// rectangle and two Input.dispatchMouseEvent calls for that rectangle.
(function exposeDebuggerActivitySpike(scope) {
  const PROTOCOL_VERSION = "1.3";
  const ACTIVITY_RECT_EXPRESSION = `(() => {
    const labels = new Set(["アクティビティを見る", "View activity"]);
    const target = Array.from(document.querySelectorAll('[role="button"]'))
      .find((element) => labels.has((element.innerText || "").replace(/\\s+/g, " ").trim()));
    if (!target) return null;
    const rect = target.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0
      ? { x: rect.x, y: rect.y, width: rect.width, height: rect.height } : null;
  })()`;

  function isCanonicalPostUrl(value) {
    if (typeof value !== "string") return false;
    try {
      const parsed = new URL(value);
      return parsed.protocol === "https:" && parsed.hostname === "www.threads.net"
        && /^\/@[A-Za-z0-9._-]+\/post\/[A-Za-z0-9._-]+$/.test(parsed.pathname)
        && !parsed.search && !parsed.hash;
    } catch (_error) { return false; }
  }

  function pointFromEvaluation(response) {
    const rect = response && response.result && response.result.value;
    if (!rect || ![rect.x, rect.y, rect.width, rect.height]
      .every((value) => typeof value === "number" && Number.isFinite(value))
      || rect.width <= 0 || rect.height <= 0) return null;
    return { x: rect.x + rect.width / 2, y: rect.y + rect.height / 2 };
  }

  function createRunner(dependencies) {
    const { tabs, debuggerApi, waitForTabComplete, confirmActivity } = dependencies;

    async function run(postUrl) {
      if (!isCanonicalPostUrl(postUrl)) return { accepted: false, outcome: "TAB_UNAVAILABLE" };
      let tabId = null;
      let attached = false;
      try {
        const tab = await tabs.create({ url: postUrl, active: false });
        tabId = tab && tab.id;
        if (!Number.isInteger(tabId)) return { accepted: false, outcome: "TAB_UNAVAILABLE" };
        if (tab.status !== "complete") await waitForTabComplete(tabId);
        const target = { tabId };
        await debuggerApi.attach(target, PROTOCOL_VERSION);
        attached = true;
        const evaluation = await debuggerApi.sendCommand(target, "Runtime.evaluate", {
          expression: ACTIVITY_RECT_EXPRESSION, returnByValue: true,
        });
        const point = pointFromEvaluation(evaluation);
        if (!point) return { accepted: false, outcome: "TARGET_NOT_FOUND" };
        await debuggerApi.sendCommand(target, "Input.dispatchMouseEvent", {
          type: "mousePressed", x: point.x, y: point.y, button: "left", clickCount: 1,
        });
        await debuggerApi.sendCommand(target, "Input.dispatchMouseEvent", {
          type: "mouseReleased", x: point.x, y: point.y, button: "left", clickCount: 1,
        });
        const confirmation = await confirmActivity(tabId);
        return confirmation && confirmation.activitySurface === true
          ? { accepted: true, outcome: "SHEET_OBSERVED" }
          : { accepted: false, outcome: "SHEET_NOT_OBSERVED" };
      } catch (_error) {
        return {
          accepted: false,
          outcome: attached ? "DEBUGGER_COMMAND_FAILED" : "DEBUGGER_ATTACH_FAILED",
        };
      } finally {
        if (attached && tabId !== null) {
          try { await debuggerApi.detach({ tabId }); } catch (_detachError) { /* best effort */ }
        }
        if (tabId !== null) {
          try { await tabs.remove(tabId); } catch (_removeError) { /* dedicated tab only */ }
        }
      }
    }

    return Object.freeze({ run });
  }

  scope.SCE_DEBUGGER_SPIKE = Object.freeze({
    protocolVersion: PROTOCOL_VERSION,
    activityRectExpression: ACTIVITY_RECT_EXPRESSION,
    isCanonicalPostUrl, pointFromEvaluation, createRunner,
  });
})(globalThis);
