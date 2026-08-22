"use strict";

if (typeof importScripts === "function") importScripts("batch_controller.js", "debugger_spike.js");

(function exposeBackgroundTransport(scope) {
  const RECEIVER_URL = "http://127.0.0.1:8765/browser-ingest/threads";
  const PENDING_DETAILS_URL = RECEIVER_URL + "/pending-details";
  const DETAIL_FAILURE_URL = RECEIVER_URL + "/detail-failures";
  const THREAD_SEQUENCE_URL = RECEIVER_URL + "/thread-sequences";
  const DETAIL_QUEUE_SUMMARY_URL = RECEIVER_URL + "/detail-queue/summary";
  const DETAIL_BATCHES_URL = RECEIVER_URL + "/detail-batches";
  const DETAIL_QUEUE_CLAIM_URL = RECEIVER_URL + "/detail-queue/claim";
  const DETAIL_QUEUE_COMPLETE_URL = RECEIVER_URL + "/detail-queue/complete";
  const DETAIL_QUEUE_FAIL_URL = RECEIVER_URL + "/detail-queue/fail";
  const NATIVE_INPUT_SPIKE_URL = RECEIVER_URL + "/native-input-spike";
  const NATIVE_INPUT_DIAGNOSTIC_URL = RECEIVER_URL + "/native-input-diagnostic";
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

  function isSafeThreadSequence(sequence) {
    const required = [
      "root_post_url", "nodes", "detail_observation_id", "observed_at", "extractor_version",
    ];
    if (!sequence || typeof sequence !== "object" || containsForbiddenKey(sequence)
        || Object.keys(sequence).length !== required.length
        || required.some((key) => !(key in sequence))
        || !isCanonicalThreadsPostUrl(sequence.root_post_url)
        || !Array.isArray(sequence.nodes) || sequence.nodes.length < 1
        || !Number.isInteger(sequence.detail_observation_id) || sequence.detail_observation_id < 1
        || typeof sequence.observed_at !== "string" || typeof sequence.extractor_version !== "string") {
      return false;
    }
    return sequence.nodes.every((node) => {
      const nodeKeys = ["post_url", "sequence_position", "reply_to_post_url", "same_author_as_root"];
      return node && typeof node === "object" && Object.keys(node).length === nodeKeys.length
        && nodeKeys.every((key) => key in node)
        && isCanonicalThreadsPostUrl(node.post_url)
        && Number.isInteger(node.sequence_position) && node.sequence_position >= 0
        && (node.reply_to_post_url === null || isCanonicalThreadsPostUrl(node.reply_to_post_url))
        && (node.same_author_as_root === null || typeof node.same_author_as_root === "boolean");
    });
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
        observationId: Number.isInteger(payload.observation_id) ? payload.observation_id : null,
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

  async function sendThreadSequence(sequence, options = {}) {
    if (!isSafeThreadSequence(sequence)) {
      return { accepted: false, reason: "unsafe_thread_sequence" };
    }
    const origin = extensionOrigin();
    if (!origin) return { accepted: false, reason: "extension_origin_unavailable" };
    try {
      const response = await (options.fetch || fetch)(THREAD_SEQUENCE_URL, {
        method: "POST", headers: { "Content-Type": "application/json", "X-SCE-Extension-Origin": origin },
        body: JSON.stringify(sequence), cache: "no-store", credentials: "omit",
      });
      if (response.status !== 201) return { accepted: false, reason: "receiver_rejected" };
      let payload;
      try { payload = await response.json(); } catch (_error) { return { accepted: false, reason: "invalid_receiver_response" }; }
      return payload && payload.status === "accepted"
        ? { accepted: true }
        : { accepted: false, reason: "invalid_receiver_response" };
    } catch (_error) { return { accepted: false, reason: "network_error" }; }
  }

  async function durableRequest(url, method, body, options = {}) {
    const origin = extensionOrigin();
    if (!origin) return { accepted: false, reason: "extension_origin_unavailable" };
    if (body && containsForbiddenKey(body)) {
      return { accepted: false, reason: "unsafe_queue_request" };
    }
    try {
      const request = {
        method,
        headers: { "X-SCE-Extension-Origin": origin },
        cache: "no-store",
        credentials: "omit",
      };
      if (body) {
        request.headers["Content-Type"] = "application/json";
        request.body = JSON.stringify(body);
      }
      const response = await (options.fetch || fetch)(url, request);
      if (![200, 201].includes(response.status)) {
        return { accepted: false, reason: "receiver_rejected", status: response.status };
      }
      const payload = await response.json();
      return { accepted: true, payload };
    } catch (_error) {
      return { accepted: false, reason: "network_error" };
    }
  }

  async function queueSummary(batchId = null, options = {}) {
    const result = await durableRequest(DETAIL_QUEUE_SUMMARY_URL, "GET", null, options);
    if (!result.accepted) return result;
    const payload = result.payload;
    const keys = ["DETAIL_PENDING", "DETAIL_PROCESSING", "DETAIL_ENRICHED", "DETAIL_FAILED"];
    if (!payload || payload.status !== "ok" || !Number.isInteger(payload.collected_count)
        || !payload.counts || keys.some((key) => !Number.isInteger(payload.counts[key]))) {
      return { accepted: false, reason: "invalid_receiver_response" };
    }
    return {
      accepted: true,
      status: Number.isInteger(batchId) && payload.running_batch_id === batchId
        ? "RUNNING" : "COMPLETE",
      batchId,
      collectedCount: payload.collected_count,
      counts: payload.counts,
      runningBatchId: Number.isInteger(payload.running_batch_id)
        ? payload.running_batch_id : null,
    };
  }

  async function startBatch(limit = 50, options = {}) {
    if (!Number.isInteger(limit) || limit < 1 || limit > 100) {
      return { accepted: false, reason: "invalid_limit" };
    }
    const result = await durableRequest(DETAIL_BATCHES_URL, "POST", {
      action: "start", requested_items: limit, max_items: limit, retry_failed: true,
    }, options);
    if (!result.accepted) return result;
    return result.payload && result.payload.status === "accepted"
      && Number.isInteger(result.payload.batch_id)
      ? { accepted: true, batchId: result.payload.batch_id }
      : { accepted: false, reason: "invalid_receiver_response" };
  }

  async function resumeBatch(batchId, options = {}) {
    if (!Number.isInteger(batchId) || batchId < 1) {
      return { accepted: false, reason: "invalid_batch" };
    }
    const result = await durableRequest(DETAIL_BATCHES_URL, "POST", {
      action: "resume", batch_id: batchId,
    }, options);
    return result.accepted && result.payload && result.payload.status === "accepted"
      && result.payload.batch_id === batchId && result.payload.batch_status === "RUNNING"
      ? { accepted: true, batchId }
      : result.accepted ? { accepted: false, reason: "invalid_receiver_response" } : result;
  }

  async function finishBatch(batchId, stopped = false, options = {}) {
    if (!Number.isInteger(batchId) || batchId < 1 || typeof stopped !== "boolean") {
      return { accepted: false, reason: "invalid_batch" };
    }
    const result = await durableRequest(DETAIL_BATCHES_URL, "POST", {
      action: "finish", batch_id: batchId, stopped,
    }, options);
    return result.accepted && result.payload && result.payload.status === "accepted"
      ? { accepted: true, status: result.payload.batch_status }
      : result.accepted ? { accepted: false, reason: "invalid_receiver_response" } : result;
  }

  async function claimNext(batchId, options = {}) {
    if (!Number.isInteger(batchId) || batchId < 1) {
      return { accepted: false, reason: "invalid_batch" };
    }
    const result = await durableRequest(
      DETAIL_QUEUE_CLAIM_URL, "POST", { batch_id: batchId }, options,
    );
    if (!result.accepted) return result;
    const payload = result.payload;
    if (payload && payload.status === "empty") return { accepted: true, claim: null };
    const claim = payload && payload.status === "claimed" ? {
      queue_item_id: payload.queue_item_id,
      batch_id: payload.batch_id,
      attempt: payload.attempt,
      lease_version: payload.lease_version,
      post_url: payload.post_url,
    } : null;
    if (!claim || !isCanonicalThreadsPostUrl(claim.post_url)
        || [claim.queue_item_id, claim.batch_id, claim.attempt, claim.lease_version]
          .some((value) => !Number.isInteger(value) || value < 1)) {
      return { accepted: false, reason: "invalid_receiver_response" };
    }
    return { accepted: true, claim };
  }

  async function completeClaim(correlation, options = {}) {
    const result = await durableRequest(
      DETAIL_QUEUE_COMPLETE_URL, "POST", correlation, options,
    );
    return result.accepted && result.payload && result.payload.status === "completed"
      ? { accepted: true }
      : result.accepted ? { accepted: false, reason: "invalid_receiver_response" } : result;
  }

  async function failClaim(correlation, options = {}) {
    const mappings = {
      PAGE_TIMEOUT: ["TIMEOUT", "TIME_LIMIT_EXCEEDED"],
      POST_NOT_FOUND: ["PAGE_UNAVAILABLE", "POST_NOT_FOUND"],
      ACTIVITY_BUTTON_NOT_FOUND: ["EXTRACTION_FAILED", "EXPECTED_FIELD_MISSING"],
      ACTIVITY_DIALOG_TIMEOUT: ["TIMEOUT", "TIME_LIMIT_EXCEEDED"],
      VIEW_COUNT_NOT_FOUND: ["EXTRACTION_FAILED", "EXPECTED_FIELD_MISSING"],
      THREAD_SEQUENCE_NOT_OBSERVED: ["EXTRACTION_FAILED", "EXPECTED_FIELD_MISSING"],
      INGESTION_FAILED: ["VALIDATION_FAILED", "INVALID_OBSERVATION"],
      EXTRACTOR_MISMATCH: ["EXTRACTION_FAILED", "UNRECOGNIZED_PAGE"],
    };
    const failure = mappings[correlation && correlation.error_code];
    if (!failure) return { accepted: false, reason: "invalid_error_code" };
    const result = await durableRequest(DETAIL_QUEUE_FAIL_URL, "POST", {
      ...correlation,
      attempted_at: new Date().toISOString(),
      extractor_version: "threads_post_detail_extractor_v1",
      contract_version: "M3_BROWSER_DETAIL_ATTEMPT_V1",
      failure_type: failure[0],
      failure_reason: failure[1],
    }, options);
    return result.accepted && result.payload && result.payload.status === "failure_recorded"
      ? { accepted: true }
      : result.accepted ? { accepted: false, reason: "invalid_receiver_response" } : result;
  }

  scope.SCE_BACKGROUND_TRANSPORT = Object.freeze({
    receiverUrl: RECEIVER_URL,
    timeoutMilliseconds: TIMEOUT_MILLISECONDS,
    pendingDetailsUrl: PENDING_DETAILS_URL,
    detailFailureUrl: DETAIL_FAILURE_URL, threadSequenceUrl: THREAD_SEQUENCE_URL,
    sendObservation, fetchPendingDetails, sendDetailFailure, sendThreadSequence, extensionOrigin,
    queueSummary, startBatch, resumeBatch, finishBatch, claimNext, completeClaim, failClaim,
  });

  function waitForTabComplete(tabId, timeout = 15000) {
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        chrome.tabs.onUpdated.removeListener(listener);
        reject(new Error("tab_timeout"));
      }, timeout);
      function listener(updatedId, changeInfo) {
        if (updatedId !== tabId || changeInfo.status !== "complete") return;
        clearTimeout(timer);
        chrome.tabs.onUpdated.removeListener(listener);
        resolve(tabId);
      }
      chrome.tabs.onUpdated.addListener(listener);
    });
  }

  const workerResultBroker = scope.SCE_DETAIL_BATCH
    && scope.SCE_DETAIL_BATCH.createWorkerResultBroker({ timeoutMilliseconds: 15000 });
  const durableBatchMethods = [
    "queueSummary", "startBatch", "resumeBatch", "claimNext", "completeClaim", "failClaim", "finishBatch",
  ];
  const durableTransportReady = durableBatchMethods.every(
    (name) => typeof scope.SCE_BACKGROUND_TRANSPORT[name] === "function",
  );
  const batchController = scope.SCE_DETAIL_BATCH && durableTransportReady
    && scope.SCE_DETAIL_BATCH.createController({
    transport: scope.SCE_BACKGROUND_TRANSPORT,
    storage: chrome.storage.local,
    tabWorker: {
      async open(url) {
        const tab = await chrome.tabs.create({ url, active: false });
        if (!Number.isInteger(tab.id)) throw new Error("tab_id_missing");
        if (tab.status !== "complete") await waitForTabComplete(tab.id);
        return tab.id;
      },
      async navigate(tabId, url) {
        await chrome.tabs.update(tabId, { url, active: false });
        await waitForTabComplete(tabId);
        return tabId;
      },
      async extract(tabId, url) {
        return workerResultBroker.request(
          tabId, (message) => chrome.tabs.sendMessage(tabId, message), url,
        );
      },
      async close(tabId) { await chrome.tabs.remove(tabId); },
    },
  });

  let lastForegroundDebuggerSpikeAudit = null;
  const debuggerSpike = scope.SCE_DEBUGGER_SPIKE && scope.SCE_DEBUGGER_SPIKE.createRunner({
    tabs: chrome.tabs,
    windows: chrome.windows,
    debuggerApi: chrome.debugger,
    waitForTabComplete,
    async confirmActivity(tabId) {
      return chrome.tabs.sendMessage(tabId, { type: "SCE_DEBUGGER_SPIKE_CONFIRM_ACTIVITY" });
    },
    audit(record) {
      // Ephemeral foreground-spike audit only; there is intentionally no
      // receiver transport, storage write, UI read path, or persisted output.
      lastForegroundDebuggerSpikeAudit = record;
    },
  });

  async function runDebuggerActivitySpike() {
    // The candidate comes from the receiver's human-selected DETAIL_PENDING
    // set.  This neither claims an item nor changes any durable queue state.
    const pending = await fetchPendingDetails(1);
    if (!pending.accepted || pending.urls.length !== 1) {
      return { accepted: false, outcome: "TAB_UNAVAILABLE" };
    }
    return debuggerSpike.run(pending.urls[0]);
  }

  async function runForegroundDebuggerActivitySpike() {
    const pending = await fetchPendingDetails(1);
    if (!pending.accepted || pending.urls.length !== 1) {
      return { accepted: false, outcome: "TAB_UNAVAILABLE" };
    }
    lastForegroundDebuggerSpikeAudit = null;
    return debuggerSpike.run(pending.urls[0], { foreground: true });
  }

  async function runNativeInputSpike() {
    const pending = await fetchPendingDetails(1);
    if (!pending.accepted || pending.urls.length !== 1) return { accepted: false, outcome: "NATIVE_INPUT_UNAVAILABLE" };
    const tab = await chrome.tabs.create({ url: pending.urls[0], active: true });
    if (!tab || !Number.isInteger(tab.id)) return { accepted: false, outcome: "NATIVE_INPUT_UNAVAILABLE" };
    try {
      if (tab.status !== "complete") await waitForTabComplete(tab.id);
      const pointResponse = await chrome.tabs.sendMessage(tab.id, { type: "SCE_NATIVE_INPUT_SCREEN_POINT" });
      const point = pointResponse && pointResponse.point;
      if (!point || !Number.isFinite(point.x) || !Number.isFinite(point.y)) return { accepted: false, outcome: "TARGET_NOT_FOUND" };
      const origin = extensionOrigin();
      const response = await fetch(NATIVE_INPUT_SPIKE_URL, { method: "POST", headers: { "Content-Type": "application/json", "X-SCE-Extension-Origin": origin }, body: JSON.stringify({ x: point.x, y: point.y }), credentials: "omit", cache: "no-store" });
      const result = await response.json();
      if (!result || result.status === "accessibility_permission_required") return { accepted: false, outcome: "ACCESSIBILITY_PERMISSION_REQUIRED" };
      if (!result || result.status !== "clicked") return { accepted: false, outcome: "NATIVE_INPUT_FAILED" };
      const confirmation = await chrome.tabs.sendMessage(tab.id, { type: "SCE_DEBUGGER_SPIKE_CONFIRM_ACTIVITY" });
      return confirmation && confirmation.activitySurface && Number.isSafeInteger(confirmation.viewCount)
        ? { accepted: true, outcome: "NATIVE_INPUT_SHEET_OBSERVED" }
        : { accepted: false, outcome: "NATIVE_INPUT_SHEET_NOT_OBSERVED" };
    } catch (_error) { return { accepted: false, outcome: "NATIVE_INPUT_FAILED" }; }
    finally { try { await chrome.tabs.remove(tab.id); } catch (_error) {} }
  }
  async function runNativeInputDiagnostic() {
    const origin = extensionOrigin();
    try {
      const response = await fetch(NATIVE_INPUT_DIAGNOSTIC_URL, { method: "POST", headers: { "Content-Type": "application/json", "X-SCE-Extension-Origin": origin }, body: JSON.stringify({ action: "diagnose" }), credentials: "omit", cache: "no-store" });
      const value = await response.json();
      return value && typeof value.status === "string" ? { accepted: value.status === "accessibility_allowed", outcome: value.status } : { accepted: false, outcome: "bridge_failed" };
    } catch (_error) { return { accepted: false, outcome: "bridge_failed" }; }
  }

  chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    if (message && message.type === "SCE_BATCH_WORKER_RESULT" && workerResultBroker) {
      sendResponse({
        accepted: workerResultBroker.accept(message, sender),
        reason: "stale_or_wrong_tab_worker_result",
      });
      return false;
    }
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
    if (message && message.type === "SCE_DETAIL_QUEUE_STATUS") {
      queueSummary().then(sendResponse);
      return true;
    }
    if (message && message.type === "SCE_DETAIL_FAILURE") {
      sendDetailFailure(message.failure).then(sendResponse);
      return true;
    }
    if (message && message.type === "SCE_THREAD_SEQUENCE_READY") {
      sendThreadSequence(message.sequence).then(sendResponse);
      return true;
    }
    if (message && message.type === "SCE_START_DETAIL_BATCH" && batchController) {
      batchController.start(message.limit).then(sendResponse);
      return true;
    }
    if (message && message.type === "SCE_RESUME_DETAIL_BATCH" && batchController) {
      batchController.resume().then(sendResponse);
      return true;
    }
    // This is intentionally isolated from the batch controller.  It is a
    // one-post live capability spike and never claims or mutates queue state.
    if (message && message.type === "SCE_START_DEBUGGER_ACTIVITY_SPIKE" && debuggerSpike) {
      runDebuggerActivitySpike().then(sendResponse);
      return true;
    }
    if (message && message.type === "SCE_START_DEBUGGER_FOREGROUND_SPIKE" && debuggerSpike) {
      runForegroundDebuggerActivitySpike().then(sendResponse);
      return true;
    }
    if (message && message.type === "SCE_START_NATIVE_INPUT_SPIKE") { runNativeInputSpike().then(sendResponse); return true; }
    if (message && message.type === "SCE_RUN_NATIVE_INPUT_DIAGNOSTIC") { runNativeInputDiagnostic().then(sendResponse); return true; }
    return false;
  });
})(globalThis);
