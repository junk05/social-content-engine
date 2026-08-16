"use strict";

const assert = require("node:assert/strict");
const path = require("node:path");

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
};
globalThis.document = {
  querySelector(selector) { return nodes[selector]; },
  createElement(tag) { return new Node(tag); },
};
const messages = [];
let pendingResponse = {
  accepted: true,
  urls: ["https://www.threads.net/@fixture/post/Pending1"],
};
globalThis.chrome = {
  runtime: {
    lastError: null,
    sendMessage(message, callback) {
      messages.push(message);
      if (message.type === "SCE_SCAFFOLD_STATUS") {
        callback({ ready: true, stage: "M3-010" });
      } else {
        callback(pendingResponse);
      }
    },
  },
};

require(path.join(__dirname, "..", "options.js"));
assert.deepEqual(messages, [{ type: "SCE_SCAFFOLD_STATUS" }]);
assert.equal(nodes["#pending-details"].children.length, 0);
assert.equal(typeof globalThis.open, "undefined");

nodes["#load-pending"].listeners.click();
assert.deepEqual(messages[1], { type: "SCE_LOAD_PENDING_DETAILS", limit: 50 });
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
