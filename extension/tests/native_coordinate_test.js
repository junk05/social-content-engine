"use strict";

const assert = require("node:assert/strict");
const path = require("node:path");

require(path.join(__dirname, "..", "native_coordinate.js"));

const geometry = {
  point: { x: 931.8984375, y: 339 },
  diagnostics: {
    centerY: 331,
    innerHeight: 769,
    visualViewport: { offsetTop: 0, scale: 1 },
  },
};
const bounds = { left: 17, top: 38, width: 1423, height: 850 };
assert.deepEqual(
  globalThis.SCE_NATIVE_COORDINATE.calibratedScreenPoint(geometry, bounds),
  { x: 931.8984375, y: 450 },
);

geometry.diagnostics.visualViewport = { offsetTop: 10, scale: 1.5 };
assert.deepEqual(
  globalThis.SCE_NATIVE_COORDINATE.calibratedScreenPoint(geometry, bounds),
  { x: 931.8984375, y: 600.5 },
);
assert.equal(globalThis.SCE_NATIVE_COORDINATE.calibratedScreenPoint(null, bounds), null);
