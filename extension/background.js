"use strict";

(function exposeBackgroundTransport(scope) {
  const RECEIVER_URL = "http://127.0.0.1:8765/browser-ingest/threads";
  const PENDING_DETAILS_URL = RECEIVER_URL + "/pending-details";
  const DETAIL_FAILURE_URL = RECEIVER_URL + "/detail-failures";
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

  function isCanonicalThreadsPostUrl(value) {
    if (typeof value !== "string") return false;
    try {
      const parsed = new URL(value);
      return parsed.protocol === "https:"
        && parsed.hostname === "www.threads.net"
        && /^\/@[A-Za-z0-9._-]+\/post\/[A-Za-z0-9._-]+$/.test(parsed.pathname)
        && !parsed.search && !parsed.hash;
    } catch (_error) {
      return false;
    }
  }

  function extensionOrigin() {
    const id = chrome.runtime && chrome.runtime.id;
    return typeof id === "string" && /^[a-p]{32}$/.test(id)
      ? "chrome-extension://" + id : null;
  }

  async function sendObservation(observation, options = {}) {
    const fetchImpl = options.fetch || fetch;
    const timeoutMilliseconds = options.timeoutMilliseconds ?? TIMEOUT_MILLISECONDS;
    const setTimer = options.setTimeout || setTimeout;
    const clearTimer = options.clearTimeout || clearTimeout;
    if (!observation || typeof observation !== "object" || containsForbiddenKey(observation)) {
      return { accepted: false, retryable: true, reason: "unsafe_observation" };
    }
    const origin = extensionOrigin();
    if (!origin) return { accepted: false, retryable: true, reason: "extension_origin_unavailable" };
    const controller = new AbortController();
    const timer = setTimer(() => controller.abort(), timeoutMilliseconds);
    try {
      const response = await fetchImpl(RECEIVER_URL, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-SCE-Extension-Origin": origin,
        },
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

  async function fetchPendingDetails(limit = 50, options = {}) {
    if (!Number.isInteger(limit) || limit < 1 || limit > 100) {
      return { accepted: false, reason: "invalid_limit", urls: [] };
    }
    const origin = extensionOrigin();
    if (!origin) return { accepted: false, reason: "extension_origin_unavailable", urls: [] };
    const fetchImpl = options.fetch || fetch;
    try {
      const response = await fetchImpl(PENDING_DETAILS_URL + "?limit=" + limit, {
        method: "GET",
        headers: { "X-SCE-Extension-Origin": origin },
        cache: "no-store",
        credentials: "omit",
      });
      if (response.status !== 200) {
        return { accepted: false, reason: "receiver_rejected", status: response.status, urls: [] };
      }
      const payload = await response.json();
      if (!payload || payload.status !== "ok" || !Array.isArray(payload.urls)
          || payload.urls.some((url) => !isCanonicalThreadsPostUrl(url))) {
        return { accepted: false, reason: "invalid_receiver_response", urls: [] };
      }
      return { accepted: true, urls: payload.urls.slice(0, limit) };
    } catch (_error) {
      return { accepted: false, reason: "network_error", urls: [] };
    }
  }

  async function sendDetailFailure(failure, options = {}) {
    const required = [
      "post_url", "attempted_at", "extractor_version", "contract_version",
      "failure_type", "failure_reason",
    ];
    if (!failure || typeof failure !== "object" || containsForbiddenKey(failure)
        || Object.keys(failure).length !== required.length
        || required.some((key) => typeof failure[key] !== "string")) {
      return { accepted: false, reason: "unsafe_failure" };
    }
    const origin = extensionOrigin();
    if (!origin) return { accepted: false, reason: "extension_origin_unavailable" };
    const fetchImpl = options.fetch || fetch;
    try {
      const response = await fetchImpl(DETAIL_FAILURE_URL, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-SCE-Extension-Origin": origin,
        },
        body: JSON.stringify(failure), cache: "no-store", credentials: "omit",
      });
      return response.status === 201
        ? { accepted: true }
        : { accepted: false, reason: "receiver_rejected" };
    } catch (_error) {
      return { accepted: false, reason: "network_error" };
    }
  }

  scope.SCE_BACKGROUND_TRANSPORT = Object.freeze({
    receiverUrl: RECEIVER_URL,
    timeoutMilliseconds: TIMEOUT_MILLISECONDS,
    pendingDetailsUrl: PENDING_DETAILS_URL,
    detailFailureUrl: DETAIL_FAILURE_URL,
    sendObservation, fetchPendingDetails, sendDetailFailure, extensionOrigin,
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
    if (message && message.type === "SCE_LOAD_PENDING_DETAILS") {
      fetchPendingDetails(message.limit).then(sendResponse);
      return true;
    }
    if (message && message.type === "SCE_DETAIL_FAILURE") {
      sendDetailFailure(message.failure).then(sendResponse);
      return true;
    }
    return false;
  });
})(globalThis);
