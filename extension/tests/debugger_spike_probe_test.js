"use strict";
const assert = require("node:assert/strict");
const path = require("node:path");
const metric = { hidden: false, innerText: "閲覧数 88,386", getAttribute() { return null; } };
globalThis.document = { documentElement: {}, querySelectorAll() { return [metric]; } };
globalThis.MutationObserver = class { observe() {} disconnect() {} };
let listener;
globalThis.chrome = { runtime: { onMessage: { addListener(value) { listener = value; } } } };
require(path.join(__dirname, "..", "debugger_spike_probe.js"));
async function main() {
  const probe = globalThis.SCE_DEBUGGER_SPIKE_PROBE;
  assert.equal(probe.exactActivityMetricPresent(), true);
  assert.equal(probe.exactActivityViewCount(), 88386);
  let response;
  assert.equal(listener({ type: "SCE_DEBUGGER_SPIKE_CONFIRM_ACTIVITY" }, {}, (value) => { response = value; }), true);
  await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual(response, { activitySurface: true, viewCount: 88386 });
  assert.equal(listener({ type: "unrelated" }, {}, () => {}), false);
}
main().catch((error) => { console.error(error); process.exitCode = 1; });
