"use strict";

const assert = require("node:assert/strict");
const path = require("node:path");

class Button {
  constructor() { this.textContent = ""; this.disabled = false; this.listeners = {}; this.attributes = {}; this.style = {}; }
  setAttribute(name, value) { this.attributes[name] = value; }
  addEventListener(type, listener) { this.listeners[type] = listener; }
}

class FakeObserver {
  constructor(callback) { this.callback = callback; FakeObserver.instance = this; }
  observe(_root, options) { this.options = options; }
  disconnect() { this.disconnected = true; }
  trigger() { this.callback(); }
}

function rootFixture() {
  const card = {
    children: [], parentElement: null,
    append(child) { this.children.push(child); },
    querySelectorAll(selector) {
      if (selector === 'a[href*="/post/"]') return [permalink];
      if (selector === "time[datetime]") return [{}];
      return [];
    },
  };
  const inner = {
    parentElement: card,
    querySelectorAll(selector) { return card.querySelectorAll(selector); },
  };
  const permalink = {
    parentElement: inner,
    getAttribute() { return "/@fixture/post/Detail1"; },
  };
  const headerLink = {
    parentElement: {
      parentElement: null,
      querySelectorAll(selector) {
        if (selector === 'a[href*="/post/"]') return [headerLink];
        if (selector === "time[datetime]") return [];
        return [];
      },
    },
    getAttribute() { return "/@fixture/post/Detail1"; },
  };
  return {
    card,
    dialogs: [],
    documentElement: {},
    querySelector(selector) {
      if (selector === "[data-sce-detail-action]") return card.children.find((child) => child.attributes["data-sce-detail-action"]) || null;
      return null;
    },
    querySelectorAll(selector) {
      if (selector === '[role="dialog"], [aria-modal="true"]') return this.dialogs;
      return [headerLink, permalink];
    },
    createElement() { return new Button(); },
  };
}

const observation = {
  observation_type: "POST_DETAIL",
  post_url: "https://www.threads.net/@fixture/post/Detail1",
  public_counters: { view_count: null },
};
globalThis.SCE_THREADS_POST_DETAIL_EXTRACTOR = {
  version: "threads_post_detail_extractor_v1",
  recognizePostDetail() { return true; },
  canonicalPostUrl() { return "https://www.threads.net/@fixture/post/Detail1"; },
  activityViewCount(root) { return root.activityViews ?? null; },
  extractVisibleThreadNodes() {
    return [{
      post_url: "https://www.threads.net/@fixture/post/Detail1",
      sequence_position: 0,
      reply_to_post_url: null,
      same_author_as_root: null,
      relationship_evidence: "ROOT_DETAIL_PAGE",
    }];
  },
  async extractVisibleThreadDetails() { return []; },
  async extractPostDetail() { return observation; },
};
globalThis.location = { href: "https://www.threads.net/@fixture/post/Detail1" };
const messages = [];
const responses = [];
globalThis.chrome = {
  runtime: {
    lastError: null,
    sendMessage(message, callback) {
      messages.push(message);
      callback(responses.shift() || { accepted: true, observationId: 1 });
    },
  },
};
require(path.join(__dirname, "..", "detail_action.js"));

function fakeWindow() {
  const listeners = {};
  return {
    location: { href: location.href },
    addEventListener(name, callback) { listeners[name] = callback; },
    removeEventListener(name) { delete listeners[name]; },
  };
}

async function main() {
  const successRoot = rootFixture();
  const successButton = globalThis.SCE_DETAIL_ACTION.install(successRoot, location.href);
  assert.ok(successButton);
  assert.equal(successRoot.card.children[0], successButton, "DIV-only detail card is a valid anchor");
  assert.equal(messages.length, 0, "installation must not collect or fetch");
  await successButton.listeners.click();
  assert.equal(messages.length, 2);
  assert.equal(messages[0].type, "SCE_OBSERVATION_READY");
  assert.equal(messages[0].observation, observation);
  assert.equal(messages[1].type, "SCE_THREAD_SEQUENCE_READY");
  assert.equal(messages[1].sequence.detail_observation_id, 1);
  assert.equal(successButton.textContent, "✓ 詳細収集済み");

  const childObservation = {
    observation_type: "POST_DETAIL",
    post_url: "https://www.threads.net/@fixture/post/SelfReply1",
    public_counters: { view_count: null },
  };
  const originalNodes = globalThis.SCE_THREADS_POST_DETAIL_EXTRACTOR.extractVisibleThreadNodes;
  const originalDetails = globalThis.SCE_THREADS_POST_DETAIL_EXTRACTOR.extractVisibleThreadDetails;
  globalThis.SCE_THREADS_POST_DETAIL_EXTRACTOR.extractVisibleThreadNodes = () => [
    ...originalNodes(),
    { post_url: childObservation.post_url, sequence_position: 1,
      reply_to_post_url: null, same_author_as_root: true,
      relationship_evidence: "DOM_CONTIGUOUS_ROOT_AUTHOR_CHAIN" },
  ];
  globalThis.SCE_THREADS_POST_DETAIL_EXTRACTOR.extractVisibleThreadDetails = async () => [childObservation];
  const childRoot = rootFixture();
  const childButton = globalThis.SCE_DETAIL_ACTION.install(childRoot, location.href);
  await childButton.listeners.click();
  assert.equal(messages[2].type, "SCE_OBSERVATION_READY");
  assert.equal(messages[3].type, "SCE_OBSERVATION_READY");
  assert.equal(messages[3].observation, childObservation);
  assert.equal(messages[4].type, "SCE_THREAD_SEQUENCE_READY");
  assert.equal(messages[4].sequence.nodes.length, 2);
  globalThis.SCE_THREADS_POST_DETAIL_EXTRACTOR.extractVisibleThreadNodes = originalNodes;
  globalThis.SCE_THREADS_POST_DETAIL_EXTRACTOR.extractVisibleThreadDetails = originalDetails;

  responses.push({ accepted: false, reason: "receiver_rejected" }, { accepted: true });
  const failedRoot = rootFixture();
  const failedButton = globalThis.SCE_DETAIL_ACTION.install(failedRoot, location.href);
  await failedButton.listeners.click();
  assert.equal(messages[5].type, "SCE_OBSERVATION_READY");
  assert.equal(messages[6].type, "SCE_DETAIL_FAILURE");
  assert.equal(messages[6].failure.failure_type, "VALIDATION_FAILED");
  assert.equal(messages[6].failure.failure_reason, "INVALID_OBSERVATION");
  assert.equal(failedButton.disabled, false, "one failed URL remains independently retryable");

  responses.push({ accepted: false, reason: "network_error" }, { accepted: true });
  const networkRoot = rootFixture();
  const networkButton = globalThis.SCE_DETAIL_ACTION.install(networkRoot, location.href);
  await networkButton.listeners.click();
  assert.equal(messages[8].failure.failure_type, "NAVIGATION_FAILED");
  assert.equal(messages[8].failure.failure_reason, "NETWORK_ERROR");

  const observedRoot = rootFixture();
  let ready = false;
  const originalRecognize = globalThis.SCE_THREADS_POST_DETAIL_EXTRACTOR.recognizePostDetail;
  globalThis.SCE_THREADS_POST_DETAIL_EXTRACTOR.recognizePostDetail = () => ready;
  const stop = globalThis.SCE_DETAIL_ACTION.observe(observedRoot, fakeWindow(), FakeObserver);
  assert.equal(observedRoot.card.children.length, 0, "no action before SPA detail DOM is ready");
  ready = true;
  FakeObserver.instance.trigger();
  assert.equal(observedRoot.card.children.length, 1, "detail DOM insertion injects one explicit action");
  stop();
  assert.equal(FakeObserver.instance.disconnected, true);
  globalThis.SCE_THREADS_POST_DETAIL_EXTRACTOR.recognizePostDetail = originalRecognize;

  const activityRoot = rootFixture();
  const dialog = {
    activityViews: 64123, children: [],
    append(child) { this.children.push(child); },
    querySelector(selector) {
      return this.children.find((child) => child.attributes["data-sce-detail-activity-action"]) || null;
    },
  };
  activityRoot.dialogs.push(dialog);
  const activityButton = globalThis.SCE_DETAIL_ACTION.install(activityRoot, location.href);
  assert.ok(activityButton, "an already opened Activity dialog gets an explicit action");
  assert.equal(dialog.children[0], activityButton);
  assert.equal(activityButton.textContent, "詳細収集");
  assert.equal(messages.length, 9, "insertion into Activity never collects automatically");
  globalThis.SCE_DETAIL_ACTION.install(activityRoot, location.href);
  assert.equal(dialog.children.length, 1, "Activity action is idempotent across observer passes");
  await activityButton.listeners.click();
  assert.equal(messages.length, 11);
  assert.equal(messages[9].type, "SCE_OBSERVATION_READY");
  assert.equal(messages[10].type, "SCE_THREAD_SEQUENCE_READY");
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
