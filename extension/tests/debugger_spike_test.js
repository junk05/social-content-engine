"use strict";

const assert = require("node:assert/strict");
const path = require("node:path");
require(path.join(__dirname, "..", "debugger_spike.js"));

async function main() {
  const spike = globalThis.SCE_DEBUGGER_SPIKE;
  assert.equal(spike.isCanonicalPostUrl("https://www.threads.net/@fixture/post/Spike1"), true);
  assert.equal(spike.isCanonicalPostUrl("https://www.threads.com/@fixture/post/Spike1"), false);
  assert.deepEqual(spike.pointFromEvaluation({ result: { value: { x: 10, y: 20, width: 40, height: 12 } } }), { x: 30, y: 26 });
  assert.equal(spike.pointFromEvaluation({ result: { value: { x: 0, y: 0, width: 0, height: 1 } } }), null);
  const calls = [];
  const runner = spike.createRunner({
    tabs: { async create(options) { calls.push(["create", options]); return { id: 44, status: "complete" }; }, async remove(tabId) { calls.push(["remove", tabId]); } },
    debuggerApi: {
      async attach(target, version) { calls.push(["attach", target, version]); }, async detach(target) { calls.push(["detach", target]); },
      async sendCommand(target, command, options) { calls.push(["command", target, command, options]); return command === "Runtime.evaluate" ? { result: { value: { x: 1, y: 2, width: 30, height: 20 } } } : {}; },
    },
    async waitForTabComplete() { throw new Error("already complete"); },
    async confirmActivity(tabId) { calls.push(["confirm", tabId]); return { activitySurface: true }; },
  });
  assert.deepEqual(await runner.run("https://www.threads.net/@fixture/post/Spike1"), { accepted: true, outcome: "SHEET_OBSERVED" });
  const commands = calls.filter((call) => call[0] === "command");
  assert.deepEqual(commands.map((call) => call[2]), ["Runtime.evaluate", "Input.dispatchMouseEvent", "Input.dispatchMouseEvent"], "no Network, Storage, Cookie, DOMSnapshot, or other CDP command");
  assert.equal(commands[0][3].returnByValue, true);
  assert.match(commands[0][3].expression, /getBoundingClientRect/);
  assert.deepEqual(commands.slice(1).map((call) => call[3].type), ["mousePressed", "mouseReleased"]);
  assert.deepEqual(calls.slice(-2), [["detach", { tabId: 44 }], ["remove", 44]]);
  const notObserved = spike.createRunner({
    tabs: { async create() { return { id: 45, status: "complete" }; }, async remove() {} },
    debuggerApi: { async attach() {}, async detach() {}, async sendCommand(_target, command) { return command === "Runtime.evaluate" ? { result: { value: { x: 1, y: 1, width: 1, height: 1 } } } : {}; } },
    async waitForTabComplete() {}, async confirmActivity() { return { activitySurface: false }; },
  });
  assert.deepEqual(await notObserved.run("https://www.threads.net/@fixture/post/Spike1"), { accepted: false, outcome: "SHEET_NOT_OBSERVED" });

  const foregroundCalls = [];
  let foregroundAudit;
  const foreground = spike.createRunner({
    tabs: {
      async create(options) { foregroundCalls.push(["create", options]); return { id: 47, status: "complete" }; },
      async update(tabId, options) { foregroundCalls.push(["tab-update", tabId, options]); return { id: tabId, active: true, windowId: 9 }; },
      async get(tabId) { foregroundCalls.push(["tab-get", tabId]); return { id: tabId, url: "https://www.threads.net/@fixture/post/Spike1" }; },
      async remove(tabId) { foregroundCalls.push(["remove", tabId]); },
    },
    windows: { async update(windowId, options) { foregroundCalls.push(["window-update", windowId, options]); return { id: windowId, focused: true }; } },
    debuggerApi: {
      async attach(target) { foregroundCalls.push(["attach", target]); },
      async detach(target) { foregroundCalls.push(["detach", target]); },
      async sendCommand(target, command, options) {
        foregroundCalls.push(["command", target, command, options]);
        return command === "Runtime.evaluate" ? { result: { value: { x: 3, y: 5, width: 20, height: 10 } } } : {};
      },
    },
    async waitForTabComplete() {}, async confirmActivity() { return { activitySurface: false }; },
    audit(record) { foregroundAudit = record; },
  });
  assert.deepEqual(await foreground.run("https://www.threads.net/@fixture/post/Spike1", { foreground: true }), { accepted: false, outcome: "SHEET_NOT_OBSERVED_FOREGROUND" });
  assert.deepEqual(foregroundCalls.slice(0, 5), [
    ["create", { url: "https://www.threads.net/@fixture/post/Spike1", active: false }],
    ["tab-update", 47, { active: true }],
    ["window-update", 9, { focused: true }],
    ["tab-get", 47],
    ["attach", { tabId: 47 }],
  ]);
  assert.deepEqual(foregroundCalls.filter((call) => call[0] === "command").map((call) => call[2]), ["Runtime.evaluate", "Input.dispatchMouseEvent", "Input.dispatchMouseEvent"]);
  assert.deepEqual(foregroundAudit, {
    foreground: true,
    requestedUrl: "https://www.threads.net/@fixture/post/Spike1",
    currentUrl: "https://www.threads.net/@fixture/post/Spike1",
    targetTabActive: true,
    targetWindowFocused: true,
    buttonRect: { x: 3, y: 5, width: 20, height: 10 },
    buttonCenter: { x: 13, y: 10 },
    debuggerAttached: true,
    mousePressedSent: true,
    mouseReleasedSent: true,
    outcome: "SHEET_NOT_OBSERVED_FOREGROUND",
  });

  const noTargetCalls = [];
  const noTarget = spike.createRunner({
    tabs: { async create() { return { id: 46, status: "complete" }; }, async remove(tabId) { noTargetCalls.push(["remove", tabId]); } },
    debuggerApi: { async attach() {}, async detach(target) { noTargetCalls.push(["detach", target]); }, async sendCommand(_target, command) { return command === "Runtime.evaluate" ? { result: { value: null } } : {}; } },
    async waitForTabComplete() {}, async confirmActivity() { throw new Error("must not confirm"); },
  });
  assert.deepEqual(await noTarget.run("https://www.threads.net/@fixture/post/Spike1"), { accepted: false, outcome: "TARGET_NOT_FOUND" });
  assert.deepEqual(noTargetCalls, [["detach", { tabId: 46 }], ["remove", 46]]);
}
main().catch((error) => { console.error(error); process.exitCode = 1; });
