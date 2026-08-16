"use strict";

(function exposePatternActionController(scope) {
  const ACTION_ATTRIBUTE = "data-sce-pattern-action";
  const ACTION_VERSION = "v1";

  function defaultObservationBoundary(observation) {
    chrome.runtime.sendMessage({ type: "SCE_OBSERVATION_READY", observation }, () => {
      // M3-006 has no receiver transport. Ignore an unloaded/background boundary.
      void chrome.runtime.lastError;
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

    function cardCandidates() {
      const cards = [];
      const seen = new Set();
      for (const link of documentObject.querySelectorAll('a[href*="/post/"]')) {
        const card = link.closest('article, [role="article"]');
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
      button.addEventListener("click", async (event) => {
        event.preventDefault();
        event.stopPropagation();
        if (collectingCards.has(card)) return;
        collectingCards.add(card);
        button.disabled = true;
        try {
          const observation = await extractor.extractSearchCard(card, contextFor(card, position));
          if (observation) onObservation(observation);
        } finally {
          collectingCards.delete(card);
          button.disabled = false;
        }
      });
      card.appendChild(button);
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

    return Object.freeze({ start, stop, scan, scheduleScan });
  }

  scope.SCE_PATTERN_ACTION_INJECTION = Object.freeze({
    actionAttribute: ACTION_ATTRIBUTE,
    actionVersion: ACTION_VERSION,
    createController,
  });
})(globalThis);
