"use strict";

const assert = require("node:assert/strict");
const path = require("node:path");

class Button {
  constructor() { this.textContent = ""; this.disabled = false; this.listeners = {}; }
  setAttribute() {}
  addEventListener(type, listener) { this.listeners[type] = listener; }
}

function rootFixture() {
  const article = { children: [], append(child) { this.children.push(child); } };
  const permalink = {
    getAttribute() { return "/@fixture/post/Detail1"; },
    closest(selector) { return selector === "article" ? article : null; },
  };
  return {
    article,
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

async function main() {
  const successRoot = rootFixture();
  const successButton = globalThis.SCE_DETAIL_ACTION.install(successRoot, location.href);
  assert.ok(successButton);
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
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
