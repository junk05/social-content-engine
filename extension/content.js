"use strict";

// M3-005 exposes explicit single-card extraction only. No button injection,
// navigation, automatic scan, DOM observation, or transport occurs here.
globalThis.SCE_THREADS_COLLECTOR = Object.freeze({
  stage: "M3-007",
  extractorVersion: globalThis.SCE_THREADS_SEARCH_CARD_EXTRACTOR.version,
  extractSearchCard: globalThis.SCE_THREADS_SEARCH_CARD_EXTRACTOR.extractSearchCard,
  extractorReady: true,
  buttonReady: true,
});

const patternActionController = globalThis.SCE_PATTERN_ACTION_INJECTION.createController();
patternActionController.start();
globalThis.SCE_DETAIL_ACTION.install();
