"use strict";

(function installDetailBatchWorker(scope) {
  function waitFor(predicate, timeout = 5000) {
    return new Promise((resolve) => {
      const ready = predicate();
      if (ready) { resolve(ready); return; }
      const observer = new MutationObserver(() => {
        const value = predicate();
        if (value) { observer.disconnect(); clearTimeout(timer); resolve(value); }
      });
      observer.observe(document.documentElement, { childList: true, subtree: true });
      const timer = setTimeout(() => { observer.disconnect(); resolve(null); }, timeout);
    });
  }

  function isVisible(element) {
    return element && !element.hidden &&
      (typeof element.getAttribute !== "function" || element.getAttribute("aria-hidden") !== "true");
  }

  function labelOf(element) {
    const ariaLabel = typeof element.getAttribute === "function"
      ? element.getAttribute("aria-label") : null;
    return (ariaLabel || element.innerText || "").replace(/\s+/g, " ").trim().toLowerCase();
  }

  function closestClickable(element) {
    if (typeof element.closest === "function") {
      const resolved = element.closest('button, [role="button"], a, [tabindex]');
      if (resolved) return resolved;
    }
    // Clicking the text node itself is still useful on React's delegated
    // handlers, and makes the fallback safe for a role-less Threads control.
    return element;
  }

  function activityButton() {
    const candidates = Array.from(document.querySelectorAll(
      'button, [role="button"], a, [tabindex], div, span',
    )).filter((element) => {
      const label = labelOf(element);
      return isVisible(element) && (label.includes("activity") || label.includes("アクティビティ"));
    }).map(closestClickable);
    // Prefer the post-level control over an unrelated Activity navigation
    // control when both exist on the page.
    return candidates.find((element) => {
      const label = labelOf(element);
      return label.includes("view activity") || label.includes("アクティビティを見る");
    }) || candidates[0] || null;
  }

  function exactActivityMetricElements() {
    return Array.from(document.querySelectorAll("span, div")).filter((element) => {
      if (!isVisible(element)) return false;
      // Do not treat rounded page headers such as "表示6.4万回" as exact.
      return /^(?:閲覧数|views?|表示)\s*[:：]?\s*[0-9][0-9,]*\s*(?:回|views?)?$/i.test(labelOf(element));
    });
  }

  function activitySurface(beforeDialogs, beforeMetrics) {
    const dialog = Array.from(document.querySelectorAll('[role="dialog"], [aria-modal="true"]'))
      .find((element) => isVisible(element) && !beforeDialogs.has(element));
    if (dialog) return true;
    return exactActivityMetricElements().some((element) => !beforeMetrics.has(element));
  }

  async function extract(url) {
    const extractor = scope.SCE_THREADS_POST_DETAIL_EXTRACTOR;
    const ready = await waitFor(() => extractor.recognizePostDetail(document, url));
    if (!ready) return { ok: false, reason: "dom_not_ready" };
    const trigger = activityButton();
    if (!trigger) return { ok: false, reason: "activity_button_not_found" };
    const beforeDialogs = new Set(document.querySelectorAll('[role="dialog"], [aria-modal="true"]'));
    const beforeMetrics = new Set(exactActivityMetricElements());
    trigger.click();
    // Threads variants may expose Activity as a role-less sheet. Require a
    // click-triggered new dialog or exact metric, so an existing exact page
    // header is never mistaken for a successfully opened Activity surface.
    const surface = await waitFor(() => activitySurface(beforeDialogs, beforeMetrics), 8000);
    if (!surface) return { ok: false, reason: "activity_dialog_timeout" };
    const collectedAt = new Date().toISOString();
    const observation = await extractor.extractPostDetail(document, {
      pageUrl: url, collectedAt,
    });
    if (!observation) return { ok: false, reason: "extraction_failed" };
    const nodes = extractor.extractVisibleThreadNodes(document, url).map((node) => ({
      post_url: node.post_url, sequence_position: node.sequence_position,
      reply_to_post_url: node.reply_to_post_url, same_author_as_root: node.same_author_as_root,
    }));
    const childObservations = typeof extractor.extractVisibleThreadDetails === "function"
      ? await extractor.extractVisibleThreadDetails(document, url, collectedAt) : [];
    return { ok: true, observation, childObservations, nodes };
  }

  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (!message || message.type !== "SCE_BATCH_EXTRACT_DETAIL") return false;
    extract(message.url).then((result) => chrome.runtime.sendMessage({
      type: "SCE_BATCH_WORKER_RESULT", correlation: message.correlation, result,
    }));
    sendResponse({ accepted: true });
    return true;
  });
  scope.SCE_DETAIL_BATCH_WORKER = Object.freeze({ waitFor, activityButton, extract });
})(globalThis);
