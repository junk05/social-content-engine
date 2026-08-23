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

  function isExactActivityLabel(label) {
    // Do not use substring matching here.  Ancestor divs on Threads include
    // the complete post card text, including the extension's Pattern button;
    // clicking those ancestors can invoke the wrong control.
    return label === "activity" ||
      label === "view activity" ||
      label === "アクティビティ" ||
      label === "アクティビティを見る";
  }

  function activityButton() {
    const candidates = Array.from(document.querySelectorAll(
      'button, [role="button"], a, [tabindex], div, span',
    )).filter((element) => {
      const label = labelOf(element);
      return isVisible(element) && isExactActivityLabel(label);
    });
    // Click the exact labelled element itself.  Native click events bubble to
    // a React-delegated parent, while avoiding broad clickable ancestors.
    return candidates.find((element) => {
      const label = labelOf(element);
      return label === "view activity" || label === "アクティビティを見る";
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

  async function extract(url, domReadyTimeoutMilliseconds = 8000) {
    const extractor = scope.SCE_THREADS_POST_DETAIL_EXTRACTOR;
    const ready = await waitFor(
      () => extractor.recognizePostDetail(document, url), domReadyTimeoutMilliseconds,
    );
    if (!ready) return { ok: false, reason: "dom_not_ready" };
    const collectedAt = new Date().toISOString();
    const observation = await extractor.extractPostDetail(document, {
      pageUrl: url, collectedAt,
    });
    if (!observation) return { ok: false, reason: "extraction_failed" };
    // A root `1 / N` indicator proves the page has a multi-node sequence but
    // not that a relationship exists. Wait only for visible DOM nodes to
    // render; branch eligibility remains wholly inside the extractor.
    const rootIndicator = typeof extractor.visibleSequenceIndicator === "function"
      ? extractor.visibleSequenceIndicator(document) : null;
    if (rootIndicator && rootIndicator.thread_position === 1 && rootIndicator.thread_total > 1) {
      await waitFor(
        () => extractor.extractVisibleThreadNodes(document, url).length >= rootIndicator.thread_total,
        domReadyTimeoutMilliseconds,
      );
    }
    const nodes = extractor.extractVisibleThreadNodes(document, url).map((node) => ({
      post_url: node.post_url, sequence_position: node.sequence_position,
      reply_to_post_url: node.reply_to_post_url, same_author_as_root: node.same_author_as_root,
      relationship_evidence: node.relationship_evidence,
    }));
    const childObservations = typeof extractor.extractVisibleThreadDetails === "function"
      ? await extractor.extractVisibleThreadDetails(document, url, collectedAt) : [];
    const threadDiagnostic = typeof extractor.threadExtractionDiagnostic === "function"
      ? extractor.threadExtractionDiagnostic(document, url) : null;
    return { ok: true, observation, childObservations, nodes, threadDiagnostic };
  }

  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (!message || message.type !== "SCE_BATCH_EXTRACT_DETAIL") return false;
    const domReadyTimeoutMilliseconds = Number.isInteger(message.domReadyTimeoutMilliseconds)
      && message.domReadyTimeoutMilliseconds >= 1000
      && message.domReadyTimeoutMilliseconds <= 30000
      ? message.domReadyTimeoutMilliseconds : 8000;
    extract(message.url, domReadyTimeoutMilliseconds).then((result) => chrome.runtime.sendMessage({
      type: "SCE_BATCH_WORKER_RESULT", correlation: message.correlation, result,
    }));
    sendResponse({ accepted: true });
    return true;
  });
  scope.SCE_DETAIL_BATCH_WORKER = Object.freeze({ waitFor, activityButton, extract });
})(globalThis);
