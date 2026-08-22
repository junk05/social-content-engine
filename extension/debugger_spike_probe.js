"use strict";

// Read-only Activity confirmation and bounded structural diagnosis. Arbitrary
// page text, source identity, URL, DOM dumps, and browser state never enter the
// diagnostic result.
(function installDebuggerSpikeProbe(scope) {
  const LABEL_PATTERN = /(?:閲覧数|ビュー|views?|表示)/i;

  function isVisible(element) {
    if (!element || element.hidden || element.getAttribute("aria-hidden") === "true") return false;
    const style = typeof getComputedStyle === "function" ? getComputedStyle(element) : null;
    if (style && (style.display === "none" || style.visibility === "hidden")) return false;
    return typeof element.getClientRects !== "function" || element.getClientRects().length > 0;
  }

  function normalizedText(element) {
    const rendered = typeof element.innerText === "string" ? element.innerText : "";
    const fallback = typeof element.textContent === "string" ? element.textContent : "";
    return (rendered || fallback).replace(/\s+/g, " ").trim();
  }

  function exactActivityViewCount() {
    const extractor = scope.SCE_THREADS_POST_DETAIL_EXTRACTOR;
    return extractor && typeof extractor.visibleActivityViewCount === "function"
      ? extractor.visibleActivityViewCount(document) : null;
  }

  function exactActivityMetricPresent() {
    return exactActivityViewCount() !== null;
  }

  function sheetRootSummary(element) {
    if (!element) return null;
    let depth = 0;
    for (let node = element; node && node !== document.body; node = node.parentElement) depth += 1;
    return {
      tag: String(element.tagName || "UNKNOWN").toUpperCase(),
      role: element.getAttribute("role"),
      ariaModal: element.getAttribute("aria-modal"),
      visible: isVisible(element),
      bodyPortal: element.parentElement === document.body,
      depth,
    };
  }

  function relativeStructuralPath(element, root) {
    const parts = [];
    for (let node = element; node && node !== root && parts.length < 8; node = node.parentElement) {
      const siblings = node.parentElement ? Array.from(node.parentElement.children || []) : [];
      parts.push(`${String(node.tagName || "UNKNOWN").toUpperCase()}[${siblings.indexOf(node)}]`);
    }
    return parts.reverse().join("/");
  }

  function metricKind(text) {
    if (/(?:閲覧|ビュー|表示|views?)/i.test(text)) return "VIEWS";
    if (/(?:いいね|likes?)/i.test(text)) return "LIKES";
    if (/(?:返信|リプライ|repl(?:y|ies))/i.test(text)) return "REPLIES";
    if (/(?:再投稿|reposts?)/i.test(text)) return "REPOSTS";
    if (/(?:引用|quotes?)/i.test(text)) return "QUOTES";
    return null;
  }

  function structuralMetricNodes(root) {
    if (!root) return [];
    const result = [];
    for (const element of root.querySelectorAll("span, div, p")) {
      if (!isVisible(element)) continue;
      const text = normalizedText(element);
      if (!text || text.length > 80) continue;
      const kind = metricKind(text);
      const exactInteger = /^(?:0|[1-9][0-9]{0,2}(?:,[0-9]{3})*|[1-9][0-9]*)$/.test(text);
      const formattedNumber = /^[0-9][0-9,.]*\s*(?:万|千|億|[KMB]|回)?$/i.test(text);
      if (!kind && !exactInteger && !formattedNumber) continue;
      result.push({
        kind: kind || (exactInteger ? "EXACT_INTEGER" : "FORMATTED_NUMBER"),
        value: exactInteger ? Number(text.replaceAll(",", "")) : null,
        numericShape: formattedNumber && !exactInteger
          ? text.replace(/[0-9]/g, "#").replace(/[,.]/g, ".") : null,
        hasDigits: /[0-9]/.test(text),
        textLength: text.length,
        tag: String(element.tagName || "UNKNOWN").toUpperCase(),
        path: relativeStructuralPath(element, root),
        childCount: element.children ? element.children.length : 0,
      });
      if (result.length >= 60) break;
    }
    return result;
  }

  function activityDomDiagnostic(timedOut = false) {
    const dialogs = Array.from(document.querySelectorAll('[role="dialog"], [aria-modal="true"]'));
    const all = Array.from(document.querySelectorAll("*"));
    const labelElements = all.filter((element) => LABEL_PATTERN.test(normalizedText(element)));
    const visibleLabels = labelElements.filter(isVisible);
    const exactValue = exactActivityViewCount();
    const splitLabels = visibleLabels.filter((element) =>
      /^(?:閲覧数|ビュー|views?|表示)$/i.test(normalizedText(element)));
    const openShadowRoots = all.filter((element) => element.shadowRoot).length;
    const visibleDialogs = dialogs.filter(isVisible);
    const root = visibleDialogs[visibleDialogs.length - 1]
      || (visibleLabels[0] && visibleLabels[0].closest
        ? visibleLabels[0].closest('[role="dialog"], [aria-modal="true"]') : null);
    return {
      timedOut,
      dialogCandidates: dialogs.length,
      visibleDialogs: visibleDialogs.length,
      activityLabelCandidates: labelElements.length,
      visibleActivityLabels: visibleLabels.length,
      splitLabelCandidates: splitLabels.length,
      exactValueFound: Number.isSafeInteger(exactValue),
      iframeCount: document.querySelectorAll("iframe").length,
      openShadowRootCount: openShadowRoots,
      sheetRoot: sheetRootSummary(root),
      metricNodes: structuralMetricNodes(root),
    };
  }

  function waitForActivityResult(timeout = 12000) {
    return new Promise((resolve) => {
      let interval = null;
      let timer = null;
      const observer = new MutationObserver(inspect);
      function cleanup() {
        observer.disconnect();
        if (interval !== null) clearInterval(interval);
        if (timer !== null) clearTimeout(timer);
      }
      function inspect() {
        const viewCount = exactActivityViewCount();
        if (!Number.isSafeInteger(viewCount)) return false;
        cleanup();
        resolve({ activitySurface: true, viewCount, diagnostics: activityDomDiagnostic(false) });
        return true;
      }
      if (inspect()) return;
      observer.observe(document.documentElement, {
        childList: true, subtree: true, attributes: true,
        attributeFilter: ["hidden", "aria-hidden", "style", "class"],
      });
      interval = setInterval(inspect, 200);
      timer = setTimeout(() => {
        cleanup();
        const diagnostics = activityDomDiagnostic(true);
        resolve({
          activitySurface: diagnostics.visibleDialogs > 0
            || diagnostics.visibleActivityLabels > 0,
          viewCount: null,
          diagnostics,
        });
      }, timeout);
    });
  }

  async function extractOpenActivity() {
    const result = await waitForActivityResult();
    if (!Number.isSafeInteger(result.viewCount)) return result;
    const extractor = scope.SCE_THREADS_POST_DETAIL_EXTRACTOR;
    const collectedAt = new Date().toISOString();
    const observation = await extractor.extractPostDetail(document, {
      pageUrl: location.href,
      collectedAt,
    });
    if (!observation || observation.public_counters.view_count !== result.viewCount) {
      return { ...result, observation: null, nodes: [] };
    }
    const nodes = extractor.extractVisibleThreadNodes(document, location.href).map((node) => ({
      post_url: node.post_url,
      sequence_position: node.sequence_position,
      reply_to_post_url: node.reply_to_post_url,
      same_author_as_root: node.same_author_as_root,
    }));
    return { ...result, observation, nodes };
  }

  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (!message) return false;
    if (message.type === "SCE_DEBUGGER_SPIKE_CONFIRM_ACTIVITY") {
      waitForActivityResult().then(sendResponse);
      return true;
    }
    if (message.type === "SCE_NATIVE_INPUT_EXTRACT_OPEN_ACTIVITY") {
      extractOpenActivity().then(sendResponse);
      return true;
    }
    return false;
  });

  scope.SCE_DEBUGGER_SPIKE_PROBE = Object.freeze({
    exactActivityMetricPresent,
    exactActivityViewCount,
    activityDomDiagnostic,
    structuralMetricNodes,
    waitForActivityResult,
    extractOpenActivity,
  });
})(globalThis);
