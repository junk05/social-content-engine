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

  function activityButton() {
    return Array.from(document.querySelectorAll('button, [role="button"]')).find((element) => {
      const label = (element.getAttribute("aria-label") || element.innerText || "").toLowerCase();
      return label.includes("activity") || label.includes("アクティビティ");
    }) || null;
  }

  async function extract(url) {
    const extractor = scope.SCE_THREADS_POST_DETAIL_EXTRACTOR;
    const ready = await waitFor(() => extractor.recognizePostDetail(document, url));
    if (!ready) return { ok: false, reason: "dom_not_ready" };
    const trigger = activityButton();
    if (!trigger) return { ok: false, reason: "activity_button_not_found" };
    trigger.click();
    const dialog = await waitFor(
      () => document.querySelector('[role="dialog"], [aria-modal="true"]'), 2000,
    );
    if (!dialog) return { ok: false, reason: "activity_dialog_timeout" };
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
