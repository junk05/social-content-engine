"use strict";

const assert = require("node:assert/strict");
const path = require("node:path");

let activityClicked = 0;
let dialogEnabled = true;
const dialog = {};
const activity = {
  innerText: "Activity",
  getAttribute(name) { return name === "aria-label" ? "Activity" : null; },
  click() { activityClicked += 1; },
};
globalThis.document = {
  documentElement: {},
  querySelectorAll(selector) {
    if (selector.includes("button")) return [activity];
    if (selector.includes("dialog")) return dialogEnabled && activityClicked > 0 ? [dialog] : [];
    return [];
  },
  querySelector(selector) { return selector.includes("dialog") && dialogEnabled && activityClicked > 0 ? dialog : null; },
};
globalThis.MutationObserver = class { observe() {} disconnect() {} };
let listener;
const runtimeMessages = [];
globalThis.chrome = { runtime: {
  onMessage: { addListener(value) { listener = value; } },
  async sendMessage(value) { runtimeMessages.push(value); },
} };
const calls = [];
globalThis.SCE_THREADS_POST_DETAIL_EXTRACTOR = {
  recognizePostDetail(_root, url) { calls.push(["recognize", url]); return true; },
  async extractPostDetail(_root, context) {
    calls.push(["extract", context.pageUrl]);
    return { post_url: context.pageUrl, collected_at: context.collectedAt,
      text: "full visible fixture text", public_counters: { view_count: 123 } };
  },
  extractVisibleThreadNodes() {
    calls.push(["sequence"]);
    return [{ post_url: "https://www.threads.net/@fixture/post/Batch1", sequence_position: 0,
      reply_to_post_url: null, same_author_as_root: null,
      relationship_evidence: "ROOT_DETAIL_PAGE" }];
  },
  async extractVisibleThreadDetails() {
    return [{ post_url: "https://www.threads.net/@fixture/post/Child1" }];
  },
  visibleActivityViewCount() { return null; },
};
require(path.join(__dirname, "..", "detail_batch_worker.js"));

async function main() {
  const url = "https://www.threads.net/@fixture/post/Batch1";
  const result = await globalThis.SCE_DETAIL_BATCH_WORKER.extract(url);
  assert.equal(result.ok, true);
  assert.equal(activityClicked, 0, "detail collection does not require Activity automation");
  assert.equal(result.observation.text, "full visible fixture text");
  assert.equal(result.observation.public_counters.view_count, 123);
  assert.equal(result.nodes.length, 1);
  assert.equal(result.childObservations.length, 1);
  assert.equal(calls.some((item) => item[0] === "sequence"), true);
  assert.equal(listener({ type: "UNRELATED" }, {}, () => {}), false);
  // A worker request arrives after navigation to a fresh detail document.
  activityClicked = 0;
  let acknowledgement;
  assert.equal(listener({ type: "SCE_BATCH_EXTRACT_DETAIL", url, correlation: "detail-7-1" }, {},
    (value) => { acknowledgement = value; }), true);
  assert.deepEqual(acknowledgement, { accepted: true });
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(runtimeMessages[0].correlation, "detail-7-1");
  assert.equal(runtimeMessages[0].type, "SCE_BATCH_WORKER_RESULT");

  const broadCard = {
    hidden: false,
    innerText: "アクティビティを見る Pattern収集 収集済み",
    getAttribute() { return null; },
    click() { throw new Error("a broad post card must never be clicked"); },
  };
  const exactActivity = {
    hidden: false,
    innerText: "アクティビティを見る",
    getAttribute() { return null; },
    click() {},
  };
  const originalCandidates = document.querySelectorAll;
  document.querySelectorAll = (selector) => selector.includes("button") ? [broadCard, exactActivity] : [];
  assert.equal(globalThis.SCE_DETAIL_BATCH_WORKER.activityButton(), exactActivity,
    "only an exact Activity label is eligible; a post-card ancestor is not");
  document.querySelectorAll = originalCandidates;

  const originalRecognize = globalThis.SCE_THREADS_POST_DETAIL_EXTRACTOR.recognizePostDetail;
  globalThis.SCE_THREADS_POST_DETAIL_EXTRACTOR.recognizePostDetail = () => false;
  const originalSetTimeout = globalThis.setTimeout;
  globalThis.setTimeout = (callback) => { queueMicrotask(callback); return 1; };
  assert.deepEqual(await globalThis.SCE_DETAIL_BATCH_WORKER.extract(url), {
    ok: false, reason: "dom_not_ready",
  });
  globalThis.setTimeout = originalSetTimeout;
  globalThis.SCE_THREADS_POST_DETAIL_EXTRACTOR.recognizePostDetail = originalRecognize;
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
