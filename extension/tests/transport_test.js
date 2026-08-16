"use strict";

const assert = require("node:assert/strict");
const path = require("node:path");

globalThis.chrome = { runtime: { onMessage: { addListener(listener) { this.listener = listener; } } } };
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
    accepted: true, retryable: false, observationStatus: "DETAIL_PENDING",
  });
  assert.equal(request.url, transport.receiverUrl);
  assert.equal(request.options.method, "POST");
  assert.equal(request.options.credentials, "omit");
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

  let messageResponse;
  globalThis.fetch = async () => { throw new Error("receiver unavailable fixture"); };
  const asyncResult = chrome.runtime.onMessage.listener(
    { type: "SCE_OBSERVATION_READY", observation }, {},
    (value) => { messageResponse = value; },
  );
  assert.equal(asyncResult, true);
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.equal(messageResponse.accepted, false, "unavailable live receiver remains a safe failure");
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
