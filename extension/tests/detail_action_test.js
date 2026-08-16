"use strict";

const assert = require("node:assert/strict");
const path = require("node:path");

class Button {
  constructor() { this.textContent = ""; this.disabled = false; this.listeners = {}; }
  setAttribute() {}
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
  return {
    card,
    documentElement: {},
    querySelector() { return null; },
    querySelectorAll() { return [permalink]; },
    createElement() { return new Button(); },
  };
}

const observation = { observation_type: "POST_DETAIL", public_counters: { view_count: null } };
globalThis.SCE_THREADS_POST_DETAIL_EXTRACTOR = {
  version: "threads_post_detail_extractor_v1",
  recognizePostDetail() { return true; },
  canonicalPostUrl() { return "https://www.threads.net/@fixture/post/Detail1"; },
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
      callback(responses.shift() || { accepted: true });
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
  assert.equal(messages.length, 1);
  assert.equal(messages[0].type, "SCE_OBSERVATION_READY");
  assert.equal(messages[0].observation, observation);
  assert.equal(successButton.textContent, "✓ 詳細収集済み");

  responses.push({ accepted: false, reason: "receiver_rejected" }, { accepted: true });
  const failedRoot = rootFixture();
  const failedButton = globalThis.SCE_DETAIL_ACTION.install(failedRoot, location.href);
  await failedButton.listeners.click();
  assert.equal(messages[1].type, "SCE_OBSERVATION_READY");
  assert.equal(messages[2].type, "SCE_DETAIL_FAILURE");
  assert.equal(messages[2].failure.failure_type, "VALIDATION_FAILED");
  assert.equal(messages[2].failure.failure_reason, "INVALID_OBSERVATION");
  assert.equal(failedButton.disabled, false, "one failed URL remains independently retryable");

  responses.push({ accepted: false, reason: "network_error" }, { accepted: true });
  const networkRoot = rootFixture();
  const networkButton = globalThis.SCE_DETAIL_ACTION.install(networkRoot, location.href);
  await networkButton.listeners.click();
  assert.equal(messages[4].failure.failure_type, "NAVIGATION_FAILED");
  assert.equal(messages[4].failure.failure_reason, "NETWORK_ERROR");

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
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
