"use strict";

(function exposePatternActionController(scope) {
  const ACTION_ATTRIBUTE = "data-sce-pattern-action";
  const ACTION_VERSION = "v1";
  const MAX_CONTAINER_ASCENT = 6;
  const MAX_TOOLBAR_ASCENT = 2;

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
      let semanticFallback = null;
      for (let depth = 0; candidate && depth < MAX_CONTAINER_ASCENT; depth += 1) {
        const postLinks = candidate.querySelectorAll('a[href*="/post/"]');
        const times = candidate.querySelectorAll("time[datetime]");
        const boundedShape = postLinks.length === 1 && times.length === 1;
        if (boundedShape && extractor.recognizeSearchCard(candidate, windowObject.location.href)) {
          const signals = signalCount(candidate);
          if (signals >= 2) return candidate;
          if (signals >= 1 && (candidate.tagName || "").toLowerCase() === "div") return candidate;
          if (!semanticFallback && isSemanticFallback(candidate)) semanticFallback = candidate;
        }
        candidate = candidate.parentElement;
      }
      return semanticFallback;
    }

    function isVisibleControl(element) {
      return !element.hidden && element.getAttribute("aria-hidden") !== "true";
    }

    function findActionToolbar(card) {
      const controls = Array.from(card.querySelectorAll('button, [role="button"]'))
        .filter(isVisibleControl);
      for (const control of controls) {
        let candidate = control.parentElement;
        for (let depth = 0; candidate && candidate !== card && depth < MAX_TOOLBAR_ASCENT; depth += 1) {
          const grouped = Array.from(candidate.querySelectorAll('button, [role="button"]'))
            .filter(isVisibleControl);
          if (grouped.length >= 3) return candidate;
          candidate = candidate.parentElement;
        }
      }
      return null;
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
    }

    function appendPatternAction(card, button) {
      const toolbar = findActionToolbar(card);
      if (toolbar) {
        toolbar.appendChild(button);
        return;
      }
      const fallback = documentObject.createElement("div");
      fallback.setAttribute("data-sce-pattern-action-fallback", ACTION_VERSION);
      fallback.style.display = "flex";
      fallback.style.alignItems = "center";
      fallback.style.justifyContent = "flex-start";
      fallback.style.boxSizing = "border-box";
      fallback.style.width = "100%";
      fallback.style.padding = "6px 0";
      fallback.style.margin = "4px 0 0";
      fallback.appendChild(button);
      card.appendChild(fallback);
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
      start, stop, scan, scheduleScan, resolveCardContainer, findActionToolbar,
    });
  }

  scope.SCE_PATTERN_ACTION_INJECTION = Object.freeze({
    actionAttribute: ACTION_ATTRIBUTE,
    actionVersion: ACTION_VERSION,
    createController,
  });
})(globalThis);
