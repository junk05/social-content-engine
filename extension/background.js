"use strict";

if (typeof importScripts === "function") {
  importScripts("batch_controller.js", "debugger_spike.js", "native_coordinate.js");
}

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
  const COLLECTED_POSTS_URL = RECEIVER_URL + "/collected-posts";
  const DETAIL_EXCLUSION_URL = RECEIVER_URL + "/detail-exclusion";
  const NATIVE_INPUT_SPIKE_URL = RECEIVER_URL + "/native-input-spike";
  const NATIVE_INPUT_DIAGNOSTIC_URL = RECEIVER_URL + "/native-input-diagnostic";
  const NATIVE_INPUT_MOVE_URL = RECEIVER_URL + "/native-input-move";
  const TIMEOUT_MILLISECONDS = 5000;
  const PAGE_LOAD_TIMEOUT_MILLISECONDS = 15000;
  const DOM_READY_TIMEOUT_MILLISECONDS = 8000;
  const EXTRACTION_TIMEOUT_MILLISECONDS = 20000;
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
      "root_post_url", "nodes", "detail_observation_id", "observed_at", "extractor_version", "thread_extraction",
    ];
    if (!sequence || typeof sequence !== "object" || containsForbiddenKey(sequence)
        || Object.keys(sequence).length !== required.length
        || required.some((key) => !(key in sequence))
        || !isCanonicalThreadsPostUrl(sequence.root_post_url)
        || !Array.isArray(sequence.nodes) || sequence.nodes.length < 1
        || !Number.isInteger(sequence.detail_observation_id) || sequence.detail_observation_id < 1
        || typeof sequence.observed_at !== "string" || typeof sequence.extractor_version !== "string"
        || !sequence.thread_extraction || typeof sequence.thread_extraction !== "object") {
      return false;
    }
    const diagnosticKeys = ["diagnostic_version", "visible_post_nodes", "discovered_candidates",
      "direct_root_author_candidates", "other_author_candidates", "root_author_after_other_boundary",
      "final_eligible_nodes", "excluded_candidates", "exclusion_reasons"];
    if (Object.keys(sequence.thread_extraction).length !== diagnosticKeys.length
        || diagnosticKeys.some((key) => !(key in sequence.thread_extraction))
        || typeof sequence.thread_extraction.diagnostic_version !== "string"
        || !sequence.thread_extraction.diagnostic_version
        || !["visible_post_nodes", "discovered_candidates", "direct_root_author_candidates",
          "other_author_candidates", "root_author_after_other_boundary", "final_eligible_nodes",
          "excluded_candidates"].every((key) => Number.isInteger(sequence.thread_extraction[key])
            && sequence.thread_extraction[key] >= 0)
        || !sequence.thread_extraction.exclusion_reasons
        || typeof sequence.thread_extraction.exclusion_reasons !== "object"
        || Array.isArray(sequence.thread_extraction.exclusion_reasons)
        || Object.values(sequence.thread_extraction.exclusion_reasons).some((value) => !Number.isInteger(value) || value < 1)) return false;
    return sequence.nodes.every((node) => {
      const nodeKeys = ["post_url", "sequence_position", "reply_to_post_url", "same_author_as_root", "relationship_evidence"];
      return node && typeof node === "object" && Object.keys(node).length === nodeKeys.length
        && nodeKeys.every((key) => key in node)
        && isCanonicalThreadsPostUrl(node.post_url)
        && Number.isInteger(node.sequence_position) && node.sequence_position >= 0
        && (node.reply_to_post_url === null || isCanonicalThreadsPostUrl(node.reply_to_post_url))
        && (node.same_author_as_root === null || typeof node.same_author_as_root === "boolean")
        && ["ROOT_DETAIL_PAGE", "DOM_CONTIGUOUS_ROOT_AUTHOR_CHAIN"].includes(node.relationship_evidence);
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
        ? { accepted: true, threadExtractionStatus: payload.thread_extraction_status }
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
      excludedCount: Number.isInteger(payload.excluded_count) ? payload.excluded_count : 0,
      runningBatchId: Number.isInteger(payload.running_batch_id)
        ? payload.running_batch_id : null,
    };
  }

  function isSafeCollectedPost(post) {
    const keys = [
      "collected_at", "author_username", "post_url", "detail_status",
      "attempt_count", "last_error", "rounded_views_raw",
      "rounded_views_normalized", "rounded_views_band", "self_reply_count",
      "display_views_raw", "display_views_normalized", "display_views_precision",
      "display_views_band",
      "enrichment_excluded", "exclusion_reason", "excluded_at",
    ];
    return post && typeof post === "object" && Object.keys(post).length === keys.length
      && keys.every((key) => key in post)
      && typeof post.collected_at === "string"
      && typeof post.author_username === "string"
      && /^[A-Za-z0-9._-]+$/.test(post.author_username)
      && isCanonicalThreadsPostUrl(post.post_url)
      && ["DETAIL_PENDING", "DETAIL_PROCESSING", "DETAIL_ENRICHED", "DETAIL_FAILED", "EXCLUDED"]
        .includes(post.detail_status)
      && Number.isInteger(post.attempt_count) && post.attempt_count >= 0
      && (post.last_error === null || typeof post.last_error === "string")
      && (post.rounded_views_raw === null || typeof post.rounded_views_raw === "string")
      && (post.rounded_views_normalized === null
        || (Number.isInteger(post.rounded_views_normalized)
          && post.rounded_views_normalized >= 0))
      && (post.rounded_views_band === null || typeof post.rounded_views_band === "string")
      && (post.display_views_raw === null || typeof post.display_views_raw === "string")
      && (post.display_views_normalized === null
        || (Number.isInteger(post.display_views_normalized)
          && post.display_views_normalized >= 0))
      && (post.display_views_precision === null
        || post.display_views_precision === "DISPLAY_EXACT")
      && (post.display_views_band === null || typeof post.display_views_band === "string")
      && (post.self_reply_count === null
        || (Number.isInteger(post.self_reply_count) && post.self_reply_count >= 0))
      && typeof post.enrichment_excluded === "boolean"
      && (post.exclusion_reason === null
        || post.exclusion_reason === "USER_EXCLUDED_SOURCE_UNAVAILABLE")
      && (post.excluded_at === null || typeof post.excluded_at === "string");
  }

  async function fetchCollectedPosts(status = "ALL", sort = "newest", limit = 200, options = {}) {
    const statuses = ["ALL", "DETAIL_PENDING", "DETAIL_FAILED", "DETAIL_ENRICHED", "EXCLUDED"];
    if (!statuses.includes(status) || !["newest", "oldest", "error_first"].includes(sort)
        || !Number.isInteger(limit) || limit < 1 || limit > 500) {
      return { accepted: false, reason: "invalid_list_request", posts: [] };
    }
    const query = "?status=" + encodeURIComponent(status)
      + "&sort=" + encodeURIComponent(sort) + "&limit=" + limit;
    const result = await durableRequest(COLLECTED_POSTS_URL + query, "GET", null, options);
    if (!result.accepted) return { ...result, posts: [] };
    const payload = result.payload;
    if (!payload || payload.status !== "ok" || !Number.isInteger(payload.count)
        || !Array.isArray(payload.posts) || payload.count !== payload.posts.length
        || payload.posts.some((post) => !isSafeCollectedPost(post))) {
      return { accepted: false, reason: "invalid_receiver_response", posts: [] };
    }
    return { accepted: true, posts: payload.posts };
  }

  async function updateDetailExclusion(action, postUrl, options = {}) {
    if (!["EXCLUDE", "REQUEUE"].includes(action) || !isCanonicalThreadsPostUrl(postUrl)) {
      return { accepted: false, reason: "invalid_exclusion_request" };
    }
    const result = await durableRequest(
      DETAIL_EXCLUSION_URL, "POST", { action, post_url: postUrl }, options,
    );
    if (!result.accepted) return result;
    const payload = result.payload;
    return payload && payload.status === "accepted"
      && typeof payload.changed === "boolean"
      && typeof payload.enrichment_excluded === "boolean"
      ? {
        accepted: true, changed: payload.changed,
        enrichmentExcluded: payload.enrichment_excluded,
      }
      : { accepted: false, reason: "invalid_receiver_response" };
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
    collectedPostsUrl: COLLECTED_POSTS_URL, detailExclusionUrl: DETAIL_EXCLUSION_URL,
    sendObservation, fetchPendingDetails, sendDetailFailure, sendThreadSequence, extensionOrigin,
    queueSummary, fetchCollectedPosts, updateDetailExclusion,
    startBatch, resumeBatch, finishBatch, claimNext, completeClaim, failClaim,
  });

  function waitForTabComplete(tabId, timeout = PAGE_LOAD_TIMEOUT_MILLISECONDS) {
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
    && scope.SCE_DETAIL_BATCH.createWorkerResultBroker({
      extractionTimeoutMilliseconds: EXTRACTION_TIMEOUT_MILLISECONDS,
    });
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
    onProgress(progress) {
      try {
        chrome.runtime.sendMessage({ type: "SCE_DETAIL_BATCH_PROGRESS", progress }, () => {
          void chrome.runtime.lastError;
        });
      } catch (_noProgressListener) {
        // Progress UI is optional and never changes durable batch execution.
      }
    },
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
          DOM_READY_TIMEOUT_MILLISECONDS,
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
      let workerWindow = null;
      if (Number.isInteger(tab.windowId)) {
        await chrome.windows.update(tab.windowId, { focused: true });
        workerWindow = await chrome.windows.get(tab.windowId);
      }
      await chrome.tabs.update(tab.id, { active: true });
      const pointResponse = await chrome.tabs.sendMessage(
        tab.id, { type: "SCE_NATIVE_INPUT_SCREEN_POINT" },
      );
      const point = scope.SCE_NATIVE_COORDINATE
        && scope.SCE_NATIVE_COORDINATE.calibratedScreenPoint(pointResponse, workerWindow);
      if (!point || !Number.isFinite(point.x) || !Number.isFinite(point.y)) return { accepted: false, outcome: "TARGET_NOT_FOUND" };
      const origin = extensionOrigin();
      const response = await fetch(NATIVE_INPUT_SPIKE_URL, { method: "POST", headers: { "Content-Type": "application/json", "X-SCE-Extension-Origin": origin }, body: JSON.stringify({ x: point.x, y: point.y }), credentials: "omit", cache: "no-store" });
      const result = await response.json();
      if (!result || result.status === "accessibility_permission_required") return { accepted: false, outcome: "ACCESSIBILITY_PERMISSION_REQUIRED" };
      if (!result || result.status !== "clicked") {
        const errors = { coordinate_out_of_bounds: "COORDINATE_OUT_OF_BOUNDS", cgevent_create_failed: "CGEVENT_CREATE_FAILED", helper_runtime_error: "HELPER_RUNTIME_ERROR" };
        return { accepted: false, outcome: errors[result && result.status] || "NATIVE_INPUT_FAILED" };
      }
      const extraction = await chrome.tabs.sendMessage(
        tab.id, { type: "SCE_NATIVE_INPUT_EXTRACT_OPEN_ACTIVITY" },
      );
      if (!extraction || !extraction.activitySurface || !extraction.observation) {
        return {
          accepted: false,
          outcome: extraction && extraction.activitySurface
            ? "NATIVE_INPUT_VIEW_NOT_EXTRACTED" : "NATIVE_INPUT_SHEET_NOT_OBSERVED",
          extractionFailure: extraction && extraction.extractionFailure,
          postDetailReadiness: extraction && extraction.postDetailReadiness,
          viewObservationStatus: extraction && extraction.viewObservationStatus,
          diagnostics: extraction && extraction.diagnostics,
        };
      }
      const ingest = await sendObservation(extraction.observation);
      if (!ingest.accepted || ingest.observationStatus !== "DETAIL_ENRICHED") {
        return {
          accepted: false,
          outcome: "NATIVE_INPUT_INGESTION_FAILED",
          diagnostics: extraction.diagnostics,
        };
      }
      if (Number.isInteger(ingest.observationId) && Array.isArray(extraction.nodes)
          && extraction.nodes.length > 0) {
        await sendThreadSequence({
          root_post_url: extraction.observation.post_url,
          nodes: extraction.nodes,
          detail_observation_id: ingest.observationId,
          observed_at: extraction.observation.collected_at,
          extractor_version: extraction.observation.extractor_version,
        });
      }
      return {
        accepted: true,
        outcome: "NATIVE_INPUT_DETAIL_ENRICHED",
        viewObservationStatus: extraction.viewObservationStatus,
        diagnostics: extraction.diagnostics,
      };
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

  async function runNativeCursorCalibration() {
    const pending = await fetchPendingDetails(1);
    if (!pending.accepted || pending.urls.length !== 1) {
      return { accepted: false, outcome: "TAB_UNAVAILABLE" };
    }
    const tab = await chrome.tabs.create({ url: pending.urls[0], active: true });
    if (!tab || !Number.isInteger(tab.id)) {
      return { accepted: false, outcome: "TAB_UNAVAILABLE" };
    }
    let keepOpen = false;
    try {
      if (tab.status !== "complete") await waitForTabComplete(tab.id);
      let workerWindow = null;
      if (Number.isInteger(tab.windowId)) {
        await chrome.windows.update(tab.windowId, { focused: true });
        workerWindow = await chrome.windows.get(tab.windowId);
      }
      await chrome.tabs.update(tab.id, { active: true });
      const geometry = await chrome.tabs.sendMessage(
        tab.id, { type: "SCE_NATIVE_INPUT_SCREEN_POINT" },
      );
      const point = scope.SCE_NATIVE_COORDINATE
        && scope.SCE_NATIVE_COORDINATE.calibratedScreenPoint(geometry, workerWindow);
      if (!point || !Number.isFinite(point.x) || !Number.isFinite(point.y)) {
        return { accepted: false, outcome: "TARGET_NOT_FOUND" };
      }
      const response = await fetch(NATIVE_INPUT_MOVE_URL, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-SCE-Extension-Origin": extensionOrigin(),
        },
        body: JSON.stringify({ action: "move_cursor", x: point.x, y: point.y }),
        credentials: "omit",
        cache: "no-store",
      });
      const result = await response.json();
      if (!result || result.status !== "cursor_moved") {
        const outcomes = {
          accessibility_permission_required: "ACCESSIBILITY_PERMISSION_REQUIRED",
          coordinate_out_of_bounds: "COORDINATE_OUT_OF_BOUNDS",
          coordinate_out_of_display_bounds: "COORDINATE_OUT_OF_DISPLAY_BOUNDS",
          cursor_move_failed: "CURSOR_MOVE_FAILED",
          cursor_position_mismatch: "CURSOR_POSITION_MISMATCH",
          already_consumed: "CALIBRATION_ALREADY_CONSUMED",
        };
        return {
          accepted: false,
          outcome: outcomes[result && result.status] || "NATIVE_INPUT_FAILED",
        };
      }
      keepOpen = true;
      const windowBounds = workerWindow ? {
        left: workerWindow.left,
        top: workerWindow.top,
        width: workerWindow.width,
        height: workerWindow.height,
        state: workerWindow.state,
      } : null;
      return {
        accepted: true,
        outcome: "CURSOR_MOVE_SENT",
        diagnostics: { ...geometry.diagnostics, screenPoint: point, windowBounds },
      };
    } catch (_error) {
      return { accepted: false, outcome: "NATIVE_INPUT_FAILED" };
    } finally {
      if (!keepOpen) {
        try { await chrome.tabs.remove(tab.id); } catch (_error) {}
      }
    }
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
    if (message && message.type === "SCE_LIST_COLLECTED_POSTS") {
      fetchCollectedPosts(message.status, message.sort, message.limit).then(sendResponse);
      return true;
    }
    if (message && message.type === "SCE_UPDATE_DETAIL_EXCLUSION") {
      updateDetailExclusion(message.action, message.postUrl).then(sendResponse);
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
    if (message && message.type === "SCE_START_NATIVE_CURSOR_CALIBRATION") {
      runNativeCursorCalibration().then(sendResponse);
      return true;
    }
    return false;
  });
})(globalThis);
