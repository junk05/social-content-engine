"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const optionsHtml = fs.readFileSync(path.join(__dirname, "..", "options.html"), "utf8");
for (const obsoleteControl of [
  "run-debugger-spike",
  "run-debugger-foreground-spike",
  "run-native-input-spike",
  "run-native-input-diagnostic",
  "run-native-cursor-calibration",
]) {
  assert.equal(optionsHtml.includes(`id="${obsoleteControl}"`), false);
}
assert.equal(optionsHtml.includes('id="start-detail-batch"'), true);
assert.equal(optionsHtml.includes('id="collected-posts"'), true);
assert.equal(optionsHtml.includes('id="export-posts-csv"'), true);
assert.equal(optionsHtml.includes('id="export-thread-csv"'), true);

class Node {
  constructor(tag = "div") {
    this.tag = tag;
    this.children = [];
    this.textContent = "";
    this.disabled = false;
    this.listeners = {};
  }
  addEventListener(type, listener) { this.listeners[type] = listener; }
  append(child) { this.children.push(child); }
  replaceChildren() { this.children = []; }
}

const nodes = {
  "#status": new Node(), "#load-pending": new Node("button"),
  "#pending-status": new Node(), "#pending-details": new Node("ul"),
  "#start-detail-batch": new Node("button"), "#resume-detail-batch": new Node("button"),
  "#batch-status": new Node(),
  "#queue-summary": new Node(),
  "#collected-filter": new Node("select"), "#collected-sort": new Node("select"),
  "#refresh-collected": new Node("button"), "#collected-status": new Node(),
  "#collected-posts": new Node("tbody"),
  "#export-posts-csv": new Node("button"), "#export-thread-csv": new Node("button"),
  "#export-status": new Node(),
};
nodes["#collected-filter"].value = "ALL";
nodes["#collected-sort"].value = "newest";
globalThis.document = {
  querySelector(selector) { return nodes[selector]; },
  createElement(tag) { return new Node(tag); },
};
const messages = [];
const exportCalls = [];
globalThis.SCE_REVIEW_EXPORT_DOWNLOAD = {
  download(kind, status) {
    exportCalls.push({ kind, status });
    return Promise.resolve({ accepted: true, filename: kind + ".csv" });
  },
};
let runtimeListener = null;
let pendingResponse = {
  accepted: true,
  urls: ["https://www.threads.net/@fixture/post/Pending1"],
};
globalThis.chrome = {
  runtime: {
    lastError: null,
    onMessage: { addListener(listener) { runtimeListener = listener; } },
    sendMessage(message, callback) {
      messages.push(message);
      if (message.type === "SCE_SCAFFOLD_STATUS") {
        callback({ ready: true, stage: "M3-010" });
      } else if (message.type === "SCE_DETAIL_QUEUE_STATUS") {
        callback({ accepted: true, collectedCount: 4, counts: {
          DETAIL_PENDING: 1, DETAIL_PROCESSING: 0, DETAIL_ENRICHED: 2, DETAIL_FAILED: 1,
        }, excludedCount: 1 });
      } else if (message.type === "SCE_LIST_COLLECTED_POSTS") {
        callback({ accepted: true, posts: [{
          collected_at: "2026-08-23T01:00:00Z",
          author_username: "fixture", post_url: "https://www.threads.net/@fixture/post/Review1",
          detail_status: "DETAIL_FAILED", attempt_count: 2, last_error: "POST_NOT_FOUND",
          rounded_views_raw: null, rounded_views_normalized: null,
          rounded_views_band: null, self_reply_count: 0,
          enrichment_excluded: false, exclusion_reason: null, excluded_at: null,
        }] });
      } else if (message.type === "SCE_UPDATE_DETAIL_EXCLUSION") {
        callback({ accepted: true, changed: true, enrichmentExcluded: true });
      } else {
        callback(pendingResponse);
      }
    },
  },
};

require(path.join(__dirname, "..", "options.js"));
assert.deepEqual(messages, [
  { type: "SCE_SCAFFOLD_STATUS" }, { type: "SCE_DETAIL_QUEUE_STATUS" },
  { type: "SCE_LIST_COLLECTED_POSTS", status: "ALL", sort: "newest", limit: 200 },
]);
assert.equal(nodes["#queue-summary"].textContent.includes("DETAIL_PENDING: 1"), true);
assert.equal(nodes["#queue-summary"].textContent.includes("除外: 1"), true);
assert.equal(nodes["#collected-posts"].children.length, 1);
assert.equal(nodes["#collected-posts"].children[0].children[0].children[0].textContent, "@fixture");
assert.equal(nodes["#collected-posts"].children[0].children[1].textContent.includes("POST_NOT_FOUND"), true);
assert.equal(nodes["#collected-posts"].children[0].children[2].textContent.includes("未観測"), true);
nodes["#export-posts-csv"].listeners.click();
nodes["#collected-filter"].value = "DETAIL_FAILED";
nodes["#export-thread-csv"].listeners.click();
assert.deepEqual(exportCalls, [
  { kind: "POSTS", status: "ALL" },
  { kind: "THREAD_NODES", status: "DETAIL_FAILED" },
]);
const excludeButton = nodes["#collected-posts"].children[0].children[3].children[1];
excludeButton.listeners.click();
assert.equal(messages.some((message) => message.type === "SCE_UPDATE_DETAIL_EXCLUSION"
  && message.action === "EXCLUDE"), true);
runtimeListener({ type: "SCE_DETAIL_BATCH_PROGRESS", progress: {
  processed: 3, total: 50, succeeded: 2, failed: 1, status: "WAITING_NEXT_ITEM",
} });
assert.equal(
  nodes["#batch-status"].textContent,
  "3 / 50件 (成功 2 / 失敗 1) — 次の投稿まで待機中",
);
assert.equal(nodes["#pending-details"].children.length, 0);
assert.equal(typeof globalThis.open, "undefined");

nodes["#load-pending"].listeners.click();
assert.deepEqual(messages[messages.length - 1], { type: "SCE_LOAD_PENDING_DETAILS", limit: 50 });
assert.equal(nodes["#pending-details"].children.length, 1);
const link = nodes["#pending-details"].children[0].children[0];
assert.equal(link.tag, "a");
assert.equal(link.href, "https://www.threads.net/@fixture/post/Pending1");
assert.equal(link.target, "_blank");
assert.equal(link.rel, "noopener noreferrer");

pendingResponse = { accepted: false, reason: "network_error", detail: "must-not-display" };
nodes["#load-pending"].listeners.click();
assert.equal(nodes["#pending-status"].textContent, "詳細待ちを読み込めませんでした。 (network_error)");
assert.equal(nodes["#pending-status"].textContent.includes("must-not-display"), false);

pendingResponse = { accepted: false, reason: "receiver_rejected", status: 403 };
nodes["#load-pending"].listeners.click();
assert.equal(nodes["#pending-status"].textContent, "詳細待ちを読み込めませんでした。 (receiver_rejected) [HTTP 403]");

pendingResponse = { accepted: true, counts: { DETAIL_ENRICHED: 2 } };
nodes["#start-detail-batch"].listeners.click();
assert.equal(messages.some((message) => message.type === "SCE_START_DETAIL_BATCH"), true);
assert.equal(nodes["#batch-status"].textContent, "詳細補完完了: 2件");

pendingResponse = { accepted: false, reason: "network_error" };
nodes["#resume-detail-batch"].listeners.click();
assert.deepEqual(messages[messages.length - 1], { type: "SCE_RESUME_DETAIL_BATCH", limit: 50 });
assert.equal(nodes["#batch-status"].textContent, "詳細バッチを完了できませんでした。再開できます。");
