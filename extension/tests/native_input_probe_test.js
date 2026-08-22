"use strict";

const assert = require("node:assert/strict");
const path = require("node:path");

globalThis.chrome = { runtime: { onMessage: { addListener() {} } } };
globalThis.window = {};
globalThis.document = {};

require(path.join(__dirname, "..", "native_input_probe.js"));

const target = {
  innerText: "アクティビティを見る",
  getBoundingClientRect() {
    return { left: 100, top: 200, width: 40, height: 20 };
  },
};
const root = { querySelectorAll() { return [target]; } };
const windowObject = {
  screenX: 10,
  screenY: 20,
  innerWidth: 1000,
  innerHeight: 700,
  outerWidth: 1016,
  outerHeight: 800,
  devicePixelRatio: 2,
  visualViewport: { offsetLeft: 0, offsetTop: 0, scale: 1 },
};

const geometry = globalThis.SCE_NATIVE_INPUT_PROBE.activityButtonGeometry(windowObject, root);
assert.deepEqual(geometry.screenPoint, { x: 138, y: 322 });
assert.equal(geometry.diagnostics.frameInsetX, 8);
assert.equal(geometry.diagnostics.browserChromeTop, 92);
assert.equal(geometry.diagnostics.devicePixelRatio, 2);

windowObject.visualViewport = { offsetLeft: 5, offsetTop: 10, scale: 1.5 };
const zoomed = globalThis.SCE_NATIVE_INPUT_PROBE.activityButtonGeometry(windowObject, root);
assert.deepEqual(zoomed.screenPoint, { x: 190.5, y: 412 });

root.querySelectorAll = () => [];
assert.equal(globalThis.SCE_NATIVE_INPUT_PROBE.activityButtonGeometry(windowObject, root), null);
