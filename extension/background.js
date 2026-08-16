"use strict";

(function exposeBackgroundTransport(scope) {
  const RECEIVER_URL = "http://127.0.0.1:8765/browser-ingest/threads";
  const TIMEOUT_MILLISECONDS = 5000;
  const FORBIDDEN_KEYS = new Set([
    "authorization", "cookie", "cookies", "access_token", "token", "password", "headers",
  ]);

  function containsForbiddenKey(value) {
    if (Array.isArray(value)) return value.some(containsForbiddenKey);
    if (!value || typeof value !== "object") return false;
    return Object.entries(value).some(
      ([key, child]) => FORBIDDEN_KEYS.has(key.toLowerCase()) || containsForbiddenKey(child),
    );
  }

  async function sendObservation(observation, options = {}) {
    const fetchImpl = options.fetch || fetch;
    const timeoutMilliseconds = options.timeoutMilliseconds ?? TIMEOUT_MILLISECONDS;
    const setTimer = options.setTimeout || setTimeout;
    const clearTimer = options.clearTimeout || clearTimeout;
    if (!observation || typeof observation !== "object" || containsForbiddenKey(observation)) {
      return { accepted: false, retryable: true, reason: "unsafe_observation" };
    }
    const controller = new AbortController();
    const timer = setTimer(() => controller.abort(), timeoutMilliseconds);
    try {
      const response = await fetchImpl(RECEIVER_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(observation),
        cache: "no-store",
        credentials: "omit",
        signal: controller.signal,
      });
      if (response.status !== 201) {
        return {
          accepted: false, retryable: true, reason: "receiver_rejected", status: response.status,
        };
      }
      let payload;
      try { payload = await response.json(); } catch (_error) {
        return { accepted: false, retryable: true, reason: "invalid_receiver_response" };
      }
      if (!payload || payload.status !== "accepted") {
        return { accepted: false, retryable: true, reason: "invalid_receiver_response" };
      }
      return {
        accepted: true,
        retryable: false,
        observationStatus: typeof payload.observation_status === "string"
          ? payload.observation_status : null,
      };
    } catch (error) {
      return {
        accepted: false,
        retryable: true,
        reason: error && error.name === "AbortError" ? "timeout" : "network_error",
      };
    } finally {
      clearTimer(timer);
    }
  }

  scope.SCE_BACKGROUND_TRANSPORT = Object.freeze({
    receiverUrl: RECEIVER_URL,
    timeoutMilliseconds: TIMEOUT_MILLISECONDS,
    sendObservation,
  });

  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (message && message.type === "SCE_SCAFFOLD_STATUS") {
      sendResponse({ ready: true, receiverUrl: RECEIVER_URL, stage: "M3-007" });
      return false;
    }
    if (message && message.type === "SCE_OBSERVATION_READY") {
      sendObservation(message.observation).then(sendResponse);
      return true;
    }
    return false;
  });
})(globalThis);
