"use strict";

const assert = require("node:assert/strict");
const path = require("node:path");

globalThis.chrome = {
  runtime: {
    id: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    onMessage: { addListener(listener) { this.listener = listener; } },
  },
};
require(path.join(__dirname, "..", "background.js"));

const transport = globalThis.SCE_BACKGROUND_TRANSPORT;
const observation = Object.freeze({
  schema_version: 1,
  source: "threads",
  post_url: "https://www.threads.net/@fixture/post/Test1",
  source_post_id: null,
  text: "sanitized",
});

function response(status, payload) {
  return { status, async json() { return payload; } };
}

async function main() {
  assert.equal(transport.receiverUrl, "http://127.0.0.1:8765/browser-ingest/threads");
  let request;
  const accepted = await transport.sendObservation(observation, {
    fetch: async (url, options) => {
      request = { url, options };
      return response(201, { status: "accepted", observation_status: "DETAIL_PENDING" });
    },
  });
  assert.deepEqual(accepted, {
    accepted: true, retryable: false, observationId: null, observationStatus: "DETAIL_PENDING",
  });
  assert.equal(request.url, transport.receiverUrl);
  assert.equal(request.options.method, "POST");
  assert.equal(request.options.credentials, "omit");
  assert.equal(request.options.headers["X-SCE-Extension-Origin"], "chrome-extension://aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa");
  assert.equal(request.options.cache, "no-store");
  assert.deepEqual(JSON.parse(request.options.body), observation, "payload must be exact");
  assert.equal(request.options.body.includes("cookie"), false);
  assert.equal(request.options.body.includes("token"), false);

  let unsafeFetchCalls = 0;
  const unsafe = await transport.sendObservation(
    { ...observation, access_token: "must-not-send" },
    { fetch: async () => { unsafeFetchCalls += 1; return response(201, {}); } },
  );
  assert.equal(unsafe.reason, "unsafe_observation");
  assert.equal(unsafeFetchCalls, 0);

  const rejected = await transport.sendObservation(observation, {
    fetch: async () => response(422, { error: "invalid_observation", detail: "do-not-expose" }),
  });
  assert.deepEqual(rejected, {
    accepted: false, retryable: true, reason: "receiver_rejected", status: 422,
  });

  const network = await transport.sendObservation(observation, {
    fetch: async () => { throw new Error("private network detail"); },
  });
  assert.deepEqual(network, { accepted: false, retryable: true, reason: "network_error" });

  const timeout = await transport.sendObservation(observation, {
    setTimeout(callback) { callback(); return 1; },
    clearTimeout() {},
    fetch: async (_url, options) => {
      if (options.signal.aborted) {
        const error = new Error("aborted");
        error.name = "AbortError";
        throw error;
      }
      return response(201, { status: "accepted" });
    },
  });
  assert.deepEqual(timeout, { accepted: false, retryable: true, reason: "timeout" });

  let pendingRequest;
  const pending = await transport.fetchPendingDetails(2, {
    fetch: async (url, options) => {
      pendingRequest = { url, options };
      return response(200, {
        status: "ok",
        urls: [
          "https://www.threads.net/@fixture/post/Pending1",
          "https://www.threads.net/@fixture/post/Pending2",
        ],
      });
    },
  });
  assert.equal(pending.accepted, true);
  assert.equal(pending.urls.length, 2);
  assert.equal(pendingRequest.options.method, "GET");
  assert.equal(pendingRequest.options.credentials, "omit");
  assert.equal(pendingRequest.options.headers["X-SCE-Extension-Origin"], "chrome-extension://aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa");
  assert.equal(pendingRequest.url, transport.pendingDetailsUrl + "?limit=2");
  assert.deepEqual(await transport.fetchPendingDetails(101), {
    accepted: false, reason: "invalid_limit", urls: [],
  });
  assert.deepEqual(await transport.fetchPendingDetails(1, {
    fetch: async () => response(200, { status: "ok", urls: ["javascript:alert(1)"] }),
  }), { accepted: false, reason: "invalid_receiver_response", urls: [] });
  assert.deepEqual(await transport.fetchPendingDetails(1, {
    fetch: async () => response(403, { error: "origin_not_allowed" }),
  }), { accepted: false, reason: "receiver_rejected", status: 403, urls: [] });

  const detailFailure = {
    post_url: "https://www.threads.net/@fixture/post/Pending1",
    attempted_at: "2026-08-16T04:00:00Z",
    extractor_version: "threads_post_detail_extractor_v1",
    contract_version: "M3_BROWSER_DETAIL_ATTEMPT_V1",
    failure_type: "TIMEOUT",
    failure_reason: "TIME_LIMIT_EXCEEDED",
  };
  let failureRequest;
  assert.deepEqual(await transport.sendDetailFailure(detailFailure, {
    fetch: async (url, options) => {
      failureRequest = { url, options };
      return response(201, { status: "failure_recorded" });
    },
  }), { accepted: true });
  assert.equal(failureRequest.url, transport.detailFailureUrl);
  assert.equal(failureRequest.options.credentials, "omit");
  assert.equal(failureRequest.options.headers["X-SCE-Extension-Origin"], "chrome-extension://aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa");
  assert.deepEqual(JSON.parse(failureRequest.options.body), detailFailure);
  assert.deepEqual(await transport.sendDetailFailure({
    ...detailFailure, cookie: "never-send",
  }), { accepted: false, reason: "unsafe_failure" });

  const threadSequence = {
    root_post_url: "https://www.threads.net/@fixture/post/Root1",
    nodes: [{
      post_url: "https://www.threads.net/@fixture/post/Root1",
      sequence_position: 0,
      reply_to_post_url: null,
      same_author_as_root: true,
    }],
    detail_observation_id: 42,
    observed_at: "2026-08-16T04:00:00Z",
    extractor_version: "threads_detail_sequence_extractor_v1",
  };
  let sequenceRequest;
  assert.deepEqual(await transport.sendThreadSequence(threadSequence, {
    fetch: async (url, options) => {
      sequenceRequest = { url, options };
      return response(201, { status: "accepted", node_count: 1 });
    },
  }), { accepted: true });
  assert.equal(sequenceRequest.url, transport.threadSequenceUrl);
  assert.equal(sequenceRequest.options.credentials, "omit");
  assert.equal(
    sequenceRequest.options.headers["X-SCE-Extension-Origin"],
    "chrome-extension://aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  );
  assert.deepEqual(JSON.parse(sequenceRequest.options.body), threadSequence);
  let unsafeSequenceFetches = 0;
  assert.deepEqual(await transport.sendThreadSequence({
    ...threadSequence, nodes: [{ ...threadSequence.nodes[0], token: "never-send" }],
  }, {
    fetch: async () => { unsafeSequenceFetches += 1; return response(201, {}); },
  }), { accepted: false, reason: "unsafe_thread_sequence" });
  assert.equal(unsafeSequenceFetches, 0);
  assert.deepEqual(await transport.sendThreadSequence(threadSequence, {
    fetch: async () => response(422, { error: "invalid_thread_sequence" }),
  }), { accepted: false, reason: "receiver_rejected" });
  assert.deepEqual(await transport.sendThreadSequence(threadSequence, {
    fetch: async () => response(201, { status: "other" }),
  }), { accepted: false, reason: "invalid_receiver_response" });

  const queueSummary = await transport.queueSummary(null, {
    fetch: async () => response(200, { status: "ok", collected_count: 5,
      running_batch_id: 7, counts: { DETAIL_PENDING: 2, DETAIL_PROCESSING: 1,
        DETAIL_ENRICHED: 1, DETAIL_FAILED: 1 } }),
  });
  assert.equal(queueSummary.accepted, true);
  assert.equal(queueSummary.collectedCount, 5);
  assert.equal(queueSummary.counts.DETAIL_PENDING, 2);
  assert.equal((await transport.queueSummary(7, {
    fetch: async () => response(200, { status: "ok", collected_count: 5,
      running_batch_id: 7, counts: { DETAIL_PENDING: 2, DETAIL_PROCESSING: 1,
        DETAIL_ENRICHED: 1, DETAIL_FAILED: 1 } }),
  })).status, "RUNNING");

  let durableRequest;
  assert.deepEqual(await transport.startBatch(5, { fetch: async (url, options) => {
    durableRequest = { url, options };
    return response(200, { status: "accepted", batch_id: 9 });
  } }), { accepted: true, batchId: 9 });
  assert.equal(durableRequest.options.credentials, "omit");
  assert.deepEqual(JSON.parse(durableRequest.options.body), {
    action: "start", requested_items: 5, max_items: 5, retry_failed: true,
  });

  const claim = await transport.claimNext(9, { fetch: async () => response(200, {
    status: "claimed", queue_item_id: 3, batch_id: 9, attempt: 1,
    lease_version: 2, post_url: "https://www.threads.net/@fixture/post/Queue1",
  }) });
  assert.equal(claim.accepted, true);
  assert.equal(claim.claim.post_url, "https://www.threads.net/@fixture/post/Queue1");
  assert.deepEqual(await transport.claimNext(9, {
    fetch: async () => response(200, { status: "empty", batch_id: 9 }),
  }), { accepted: true, claim: null });

  const correlation = { queue_item_id: 3, batch_id: 9, attempt: 1,
    lease_version: 2, detail_observation_id: 42 };
  assert.deepEqual(await transport.completeClaim(correlation, {
    fetch: async (_url, options) => {
      assert.deepEqual(JSON.parse(options.body), correlation);
      return response(200, { status: "completed" });
    },
  }), { accepted: true });
  assert.deepEqual(await transport.failClaim({ queue_item_id: 4, batch_id: 9,
    attempt: 1, lease_version: 1, error_code: "ACTIVITY_DIALOG_TIMEOUT" }, {
    fetch: async (_url, options) => {
      const body = JSON.parse(options.body);
      assert.equal(body.failure_type, "TIMEOUT");
      assert.equal(body.failure_reason, "TIME_LIMIT_EXCEEDED");
      assert.equal(body.error_code, "ACTIVITY_DIALOG_TIMEOUT");
      assert.equal(options.credentials, "omit");
      return response(201, { status: "failure_recorded" });
    },
  }), { accepted: true });
  assert.deepEqual(await transport.finishBatch(9, false, {
    fetch: async () => response(200, { status: "accepted", batch_status: "COMPLETED" }),
  }), { accepted: true, status: "COMPLETED" });

  let messageResponse;
  globalThis.fetch = async () => { throw new Error("receiver unavailable fixture"); };
  const asyncResult = chrome.runtime.onMessage.listener(
    { type: "SCE_OBSERVATION_READY", observation }, {},
    (value) => { messageResponse = value; },
  );
  assert.equal(asyncResult, true);
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.equal(messageResponse.accepted, false, "unavailable live receiver remains a safe failure");

  messageResponse = undefined;
  const sequenceResult = chrome.runtime.onMessage.listener(
    { type: "SCE_THREAD_SEQUENCE_READY", sequence: threadSequence }, {},
    (value) => { messageResponse = value; },
  );
  assert.equal(sequenceResult, true);
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.deepEqual(messageResponse, { accepted: false, reason: "network_error" });
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
