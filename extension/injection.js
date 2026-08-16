"use strict";

(function exposePatternActionController(scope) {
  const ACTION_ATTRIBUTE = "data-sce-pattern-action";
  const ACTION_VERSION = "v1";
  const MAX_CONTAINER_ASCENT = 12;
  const MAX_ACTION_ROW_ASCENT = 8;

  function defaultObservationBoundary(observation) {
    return new Promise((resolve) => {
      chrome.runtime.sendMessage({ type: "SCE_OBSERVATION_READY", observation }, (response) => {
        if (chrome.runtime.lastError || !response) {
          resolve({ accepted: false, retryable: true, reason: "message_boundary_unavailable" });
          return;
        }
        resolve(response);
      });
    });
  }

  function createController(options = {}) {
    const documentObject = options.document || document;
    const windowObject = options.window || window;
    const extractor = options.extractor || scope.SCE_THREADS_SEARCH_CARD_EXTRACTOR;
    const onObservation = options.onObservation || defaultObservationBoundary;
    const Observer = options.MutationObserver || MutationObserver;
    const delay = options.debounceMilliseconds ?? 100;
    const maximumCards = options.maximumCards ?? 100;
    const setTimer = options.setTimeout || setTimeout;
    const clearTimer = options.clearTimeout || clearTimeout;
    const pendingCards = new WeakSet();
    const collectingCards = new WeakSet();
    let timer = null;
    let lastUrl = windowObject.location.href;
    let observer = null;

    function isVisibleSignal(element) {
      return !element.hidden && element.getAttribute("aria-hidden") !== "true";
    }

    function signalCount(candidate) {
      const signals = new Set();
      for (const element of candidate.querySelectorAll('[dir="auto"], a[href*="/@"]')) {
        const href = element.getAttribute("href");
        if (href && href.includes("/post/")) continue;
        if (isVisibleSignal(element)) signals.add(element);
      }
      return signals.size;
    }

    function isSemanticFallback(candidate) {
      const tag = (candidate.tagName || "").toLowerCase();
      return tag === "article" || candidate.getAttribute("role") === "article";
    }

    function resolveCardContainer(link) {
      let candidate = link.parentElement;
      let resolved = null;
      for (let depth = 0; candidate && depth < MAX_CONTAINER_ASCENT; depth += 1) {
        const postLinks = candidate.querySelectorAll('a[href*="/post/"]');
        const times = candidate.querySelectorAll("time[datetime]");
        const boundedShape = postLinks.length >= 1 && postLinks.length <= 2 && times.length === 1;
        if (postLinks.length > 2 || times.length > 1) break;
        if (boundedShape && extractor.recognizeSearchCard(candidate, windowObject.location.href)) {
          const signals = signalCount(candidate);
          const tag = (candidate.tagName || "").toLowerCase();
          if (signals >= 2 || (signals >= 1 && tag === "div") || isSemanticFallback(candidate)) {
            resolved = candidate;
          }
        }
        candidate = candidate.parentElement;
      }
      return resolved;
    }

    function stylePatternButton(button) {
      button.style.font = "inherit";
      button.style.fontSize = "12.5px";
      button.style.lineHeight = "1.25";
      button.style.borderRadius = "999px";
      button.style.border = "1px solid currentColor";
      button.style.backgroundColor = "Canvas";
      button.style.color = "CanvasText";
      button.style.padding = "5px 10px";
      button.style.margin = "0";
      button.style.cursor = "pointer";
      button.style.maxWidth = "100%";
      button.style.zIndex = "1";
    }

    function isVisibleSvg(element) {
      if (element.hidden) return false;
      if (typeof windowObject.getComputedStyle !== "function") return true;
      const computed = windowObject.getComputedStyle(element);
      return computed.display !== "none" && computed.visibility !== "hidden";
    }

    function findActionRow(card) {
      for (const svg of card.querySelectorAll("svg")) {
        if (!isVisibleSvg(svg)) continue;
        let candidate = svg.parentElement;
        for (let depth = 0; candidate && candidate !== card && depth < MAX_ACTION_ROW_ASCENT; depth += 1) {
          const computed = typeof windowObject.getComputedStyle === "function"
            ? windowObject.getComputedStyle(candidate) : candidate.style;
          const display = computed ? computed.display : "";
          const controls = Array.from(candidate.querySelectorAll("svg")).filter(isVisibleSvg);
          const containsPostIdentity = candidate.querySelectorAll('a[href*="/post/"]').length > 0
            || candidate.querySelectorAll("time[datetime]").length > 0;
          if ((display === "flex" || display === "inline-flex")
              && controls.length >= 3 && controls.length <= 6 && !containsPostIdentity) {
            return candidate;
          }
          candidate = candidate.parentElement;
        }
      }
      return null;
    }

    function appendPatternAction(card, button) {
      const actionRow = findActionRow(card);
      if (actionRow) {
        button.style.position = "static";
        button.style.marginInlineStart = "auto";
        button.style.flexShrink = "0";
        button.style.alignSelf = "center";
        actionRow.appendChild(button);
        return;
      }
      button.style.position = "absolute";
      button.style.insetBlockEnd = "8px";
      button.style.insetInlineEnd = "8px";
      const computed = typeof windowObject.getComputedStyle === "function"
        ? windowObject.getComputedStyle(card) : null;
      const computedPosition = computed ? computed.position : card.style.position;
      if (!computedPosition || computedPosition === "static") card.style.position = "relative";
      if (!card.style.paddingBlockEnd) {
        const existingPadding = computed ? Number.parseFloat(computed.paddingBlockEnd) || 0 : 0;
        card.style.paddingBlockEnd = `${existingPadding + 40}px`;
      }
      card.appendChild(button);
    }

    function cardCandidates() {
      const cards = [];
      const seen = new Set();
      for (const link of documentObject.querySelectorAll('a[href*="/post/"]')) {
        const card = resolveCardContainer(link);
        const alreadyInjected = card && card.querySelector(`[${ACTION_ATTRIBUTE}="${ACTION_VERSION}"]`);
        if (card && !alreadyInjected && !seen.has(card) && extractor.recognizeSearchCard(card, windowObject.location.href)) {
          seen.add(card);
          cards.push(card);
          if (cards.length >= maximumCards) break;
        }
      }
      return cards;
    }

    function contextFor(card, position) {
      const pageUrl = windowObject.location.href;
      let query = null;
      try { query = new URL(pageUrl).searchParams.get("q"); } catch (_error) { /* null */ }
      return { pageUrl, query, position, collectedAt: new Date().toISOString(), card };
    }

    function inject(card, position) {
      if (pendingCards.has(card) || card.querySelector(`[${ACTION_ATTRIBUTE}="${ACTION_VERSION}"]`)) return;
      if (!extractor.recognizeSearchCard(card, windowObject.location.href)) return;
      pendingCards.add(card);
      const button = documentObject.createElement("button");
      button.type = "button";
      button.textContent = "Pattern収集";
      button.setAttribute(ACTION_ATTRIBUTE, ACTION_VERSION);
      button.setAttribute("aria-label", "このThreads投稿をPattern収集");
      stylePatternButton(button);
      button.addEventListener("click", async (event) => {
        event.preventDefault();
        event.stopPropagation();
        if (collectingCards.has(card) || button.getAttribute("data-sce-state") === "accepted") return;
        collectingCards.add(card);
        button.disabled = true;
        button.textContent = "送信中…";
        button.setAttribute("data-sce-state", "sending");
        try {
          const observation = await extractor.extractSearchCard(card, contextFor(card, position));
          const response = observation
            ? await onObservation(observation)
            : { accepted: false, retryable: true, reason: "extraction_failed" };
          if (response && response.accepted === true) {
            button.textContent = "✓ 収集済み";
            button.setAttribute("aria-label", "このThreads投稿は収集済みです");
            button.setAttribute("data-sce-state", "accepted");
          } else {
            button.textContent = "再試行";
            button.setAttribute("aria-label", "Threads投稿の収集を再試行");
            button.setAttribute("data-sce-state", "failed");
          }
        } finally {
          collectingCards.delete(card);
          button.disabled = button.getAttribute("data-sce-state") === "accepted";
        }
      });
      appendPatternAction(card, button);
    }

    function scan() {
      timer = null;
      const cards = cardCandidates();
      cards.forEach(inject);
      lastUrl = windowObject.location.href;
      if (cards.length === maximumCards) scheduleScan();
    }

    function scheduleScan() {
      if (timer !== null) clearTimer(timer);
      timer = setTimer(scan, delay);
    }

    function navigationScan() {
      if (windowObject.location.href !== lastUrl) scheduleScan();
    }

    function start() {
      if (observer) return;
      scan();
      observer = new Observer(scheduleScan);
      observer.observe(documentObject.documentElement, { childList: true, subtree: true });
      windowObject.addEventListener("popstate", navigationScan);
      windowObject.addEventListener("hashchange", navigationScan);
      if (windowObject.navigation) windowObject.navigation.addEventListener("navigate", scheduleScan);
    }

    function stop() {
      if (!observer) return;
      observer.disconnect();
      observer = null;
      if (timer !== null) clearTimer(timer);
      timer = null;
      windowObject.removeEventListener("popstate", navigationScan);
      windowObject.removeEventListener("hashchange", navigationScan);
      if (windowObject.navigation) windowObject.navigation.removeEventListener("navigate", scheduleScan);
    }

    return Object.freeze({
      start, stop, scan, scheduleScan, resolveCardContainer, findActionRow,
    });
  }

  scope.SCE_PATTERN_ACTION_INJECTION = Object.freeze({
    actionAttribute: ACTION_ATTRIBUTE,
    actionVersion: ACTION_VERSION,
    createController,
  });
})(globalThis);
