"use strict";
const assert = require("node:assert/strict");
const path = require("node:path");

const metric = {
  hidden: false,
  innerText: "閲覧数 88,386",
  textContent: "閲覧数 88,386",
  parentElement: null,
  tagName: "DIV",
  getAttribute() { return null; },
  closest() { return null; },
  children: [],
};
const numeric = {
  hidden: false, innerText: "88,386", textContent: "88,386",
  parentElement: null, tagName: "SPAN", children: [],
  getAttribute() { return null; },
};
const dialog = {
  hidden: false, innerText: "", textContent: "", parentElement: null,
  tagName: "DIV", children: [metric, numeric],
  getAttribute(name) { return name === "role" ? "dialog" : null; },
  querySelectorAll() { return [metric, numeric]; },
};
metric.parentElement = dialog;
numeric.parentElement = dialog;
globalThis.document = {
  documentElement: {}, body: {},
  querySelectorAll(selector) {
    if (selector === "*") return [dialog, metric, numeric];
    if (selector === "iframe") return [];
    if (selector.includes("dialog")) return [dialog];
    return [metric];
  },
};
globalThis.MutationObserver = class { observe() {} disconnect() {} };
globalThis.SCE_THREADS_POST_DETAIL_EXTRACTOR = {
  visibleActivityViewCount() {
    return metric.innerText.includes("88,386") ? 88386 : null;
  },
};
let listener;
globalThis.chrome = { runtime: { onMessage: { addListener(value) { listener = value; } } } };
require(path.join(__dirname, "..", "debugger_spike_probe.js"));

async function main() {
  const probe = globalThis.SCE_DEBUGGER_SPIKE_PROBE;
  assert.equal(probe.exactActivityMetricPresent(), true);
  assert.equal(probe.exactActivityViewCount(), 88386);
  const diagnostic = probe.activityDomDiagnostic();
  assert.equal(diagnostic.visibleActivityLabels, 1);
  assert.equal(diagnostic.exactValueFound, true);
  assert.equal(diagnostic.metricNodes.some((node) =>
    node.kind === "EXACT_INTEGER" && node.value === 88386), true);
  metric.innerText = "ビュー";
  metric.textContent = "ビュー";
  numeric.innerText = "8.8万";
  numeric.textContent = "8.8万";
  const localized = probe.structuralMetricNodes(dialog);
  assert.equal(localized.some((node) => node.kind === "VIEWS"), true);
  assert.equal(localized.some((node) =>
    node.kind === "FORMATTED_NUMBER" && node.numericShape === "#.#万"), true);
  metric.innerText = "閲覧数 88,386";
  metric.textContent = "閲覧数 88,386";
  numeric.innerText = "88,386";
  numeric.textContent = "88,386";
  assert.equal(Object.hasOwn(diagnostic, "text"), false);
  let response;
  assert.equal(listener(
    { type: "SCE_DEBUGGER_SPIKE_CONFIRM_ACTIVITY" }, {}, (value) => { response = value; },
  ), true);
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(response.activitySurface, true);
  assert.equal(response.viewCount, 88386);
  assert.equal(response.diagnostics.exactValueFound, true);
  assert.equal(listener({ type: "unrelated" }, {}, () => {}), false);
}
main().catch((error) => { console.error(error); process.exitCode = 1; });
