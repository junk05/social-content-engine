"use strict";

// M3-004 scaffold only. M3-006 will add explicit localhost transport.
const RECEIVER_ORIGIN = "http://127.0.0.1";

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message && message.type === "SCE_SCAFFOLD_STATUS") {
    sendResponse({ ready: false, receiverOrigin: RECEIVER_ORIGIN, stage: "M3-004" });
  }
  return false;
});
