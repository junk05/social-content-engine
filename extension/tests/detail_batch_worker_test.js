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
      reply_to_post_url: null, same_author_as_root: null }];
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
  assert.equal(activityClicked, 1, "activity is opened only inside the user-started worker request");
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

  const originalQuerySelectorAll = document.querySelectorAll;
  document.querySelectorAll = () => [];
  assert.deepEqual(await globalThis.SCE_DETAIL_BATCH_WORKER.extract(url), {
    ok: false, reason: "activity_button_not_found",
  });
  document.querySelectorAll = originalQuerySelectorAll;
  const originalQuerySelector = document.querySelector;
  const originalSetTimeout = globalThis.setTimeout;
  dialogEnabled = false;
  document.querySelector = () => null;
  globalThis.setTimeout = (callback) => { queueMicrotask(callback); return 1; };
  assert.deepEqual(await globalThis.SCE_DETAIL_BATCH_WORKER.extract(url), {
    ok: false, reason: "activity_dialog_timeout",
  });
  globalThis.setTimeout = originalSetTimeout;
  document.querySelector = originalQuerySelector;

  const originalQueryAll = document.querySelectorAll;
  const rolelessMetric = {
    hidden: false,
    innerText: "閲覧数 456",
    getAttribute() { return null; },
  };
  let clickedRoleless = false;
  const activityText = {
    hidden: false,
    innerText: "アクティビティを見る",
    getAttribute() { return null; },
    click() { clickedRoleless = true; },
  };
  document.querySelector = () => null;
  document.querySelectorAll = (selector) => {
    if (selector.includes("button")) return [activityText];
    if (selector === "span, div") return clickedRoleless ? [rolelessMetric] : [];
    return [];
  };
  assert.equal((await globalThis.SCE_DETAIL_BATCH_WORKER.extract(url)).ok, true,
    "a role-less click-triggered Activity metric is accepted");
  document.querySelectorAll = originalQueryAll;
  document.querySelector = originalQuerySelector;
  dialogEnabled = true;
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
