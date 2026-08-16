"use strict";

// M3-005 extractor-only stage. M3-006 will add explicit localhost transport.
const RECEIVER_ORIGIN = "http://127.0.0.1";

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message && message.type === "SCE_SCAFFOLD_STATUS") {
    sendResponse({ ready: false, receiverOrigin: RECEIVER_ORIGIN, stage: "M3-006" });
  }
  if (message && message.type === "SCE_OBSERVATION_READY") {
    // In-memory message boundary only. M3-007 will validate and transport it.
    sendResponse({ accepted: false, stage: "M3-006", reason: "transport_not_implemented" });
  }
  return false;
});
