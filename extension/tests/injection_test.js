"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

require(path.join(__dirname, "..", "injection.js"));

class FakeButton {
  constructor() {
    this.attributes = {};
    this.listeners = {};
    this.disabled = false;
  }
  setAttribute(name, value) { this.attributes[name] = value; }
  getAttribute(name) { return this.attributes[name] ?? null; }
  addEventListener(name, listener) { this.listeners[name] = listener; }
  async click() {
    return this.listeners.click({ preventDefault() {}, stopPropagation() {} });
  }
}

class FakeCard {
  constructor(name, recognized) {
    this.name = name;
    this.recognized = recognized;
    this.children = [];
    this.link = { closest: () => this };
  }
  querySelector(selector) {
    if (selector.includes("data-sce-pattern-action")) {
      return this.children.find((child) => child.attributes["data-sce-pattern-action"] === "v1") || null;
    }
    return this.recognized && selector === "time[datetime]" ? {} : null;
  }
  appendChild(child) { this.children.push(child); }
}

class FakeDocument {
  constructor(cards) {
    this.cards = cards;
    this.documentElement = {};
  }
  querySelectorAll() { return this.cards.filter((card) => card.recognized).map((card) => card.link); }
  createElement(name) {
    assert.equal(name, "button");
    return new FakeButton();
  }
}

class FakeObserver {
  constructor(callback) { this.callback = callback; FakeObserver.instance = this; }
  observe(_root, options) { this.options = options; }
  disconnect() { this.disconnected = true; }
  trigger() { this.callback([{ type: "childList" }]); }
}

function fakeWindow() {
  const listeners = {};
  return {
    location: { href: "https://www.threads.com/search?q=one" },
    addEventListener(name, listener) { listeners[name] = listener; },
    removeEventListener(name) { delete listeners[name]; },
    dispatch(name) { listeners[name](); },
  };
}

function fakeTimers() {
  let next = 1;
  const queued = new Map();
  return {
    set(callback) { const id = next++; queued.set(id, callback); return id; },
    clear(id) { queued.delete(id); },
    flush() { const callbacks = Array.from(queued.values()); queued.clear(); callbacks.forEach((callback) => callback()); },
    size() { return queued.size; },
  };
}

function cardsFromFixture() {
  const html = fs.readFileSync(path.join(__dirname, "fixtures", "injection_surfaces.html"), "utf8");
  assert.equal(html.includes("cookie"), false);
  return [
    new FakeCard("initial-one", html.includes('data-fixture="initial-one"')),
    new FakeCard("initial-two", html.includes('data-fixture="initial-two"')),
    new FakeCard("non-card", false),
  ];
}

async function main() {
  const cards = cardsFromFixture();
  const documentObject = new FakeDocument(cards);
  const windowObject = fakeWindow();
  const timers = fakeTimers();
  const observations = [];
  let extractionCount = 0;
  const extractor = {
    recognizeSearchCard(card) { return card.recognized; },
    async extractSearchCard(card, context) {
      extractionCount += 1;
      await Promise.resolve();
      return { source: "threads", card: card.name, page_url: context.pageUrl };
    },
  };
  const controller = globalThis.SCE_PATTERN_ACTION_INJECTION.createController({
    document: documentObject, window: windowObject, extractor,
    MutationObserver: FakeObserver, onObservation: (value) => {
      observations.push(value);
      return { accepted: true, observationStatus: "DETAIL_PENDING" };
    },
    setTimeout: timers.set, clearTimeout: timers.clear,
  });

  controller.start();
  assert.deepEqual(cards.map((card) => card.children.length), [1, 1, 0]);
  assert.equal(extractionCount, 0, "initial scan must not collect automatically");
  controller.scan();
  assert.deepEqual(cards.map((card) => card.children.length), [1, 1, 0]);

  const dynamic = new FakeCard("dynamic", true);
  documentObject.cards.push(dynamic);
  FakeObserver.instance.trigger();
  FakeObserver.instance.trigger();
  assert.equal(timers.size(), 1, "mutation scans must be debounced");
  timers.flush();
  assert.equal(dynamic.children.length, 1);
  assert.equal(extractionCount, 0, "dynamic scan must not collect automatically");

  windowObject.location.href = "https://www.threads.com/search?q=two";
  windowObject.dispatch("popstate");
  assert.equal(timers.size(), 1);
  timers.flush();
  assert.deepEqual(documentObject.cards.map((card) => card.children.length), [1, 1, 0, 1]);

  await Promise.all([dynamic.children[0].click(), dynamic.children[0].click()]);
  assert.equal(extractionCount, 1, "concurrent duplicate clicks must collapse");
  assert.equal(observations.length, 1);
  assert.equal(observations[0].page_url, "https://www.threads.com/search?q=two");
  assert.equal(dynamic.children[0].disabled, true);
  assert.equal(dynamic.children[0].textContent, "✓ 収集済み");
  await dynamic.children[0].click();
  assert.equal(extractionCount, 1, "accepted card must not send twice");

  const retryCard = new FakeCard("retry", true);
  const retryDocument = new FakeDocument([retryCard]);
  let retryCalls = 0;
  const retryController = globalThis.SCE_PATTERN_ACTION_INJECTION.createController({
    document: retryDocument, window: windowObject, extractor,
    MutationObserver: FakeObserver,
    onObservation: () => {
      retryCalls += 1;
      return retryCalls === 1 ? { accepted: false, retryable: true, reason: "network_error" }
        : { accepted: true, observationStatus: "DETAIL_PENDING" };
    },
    setTimeout: timers.set, clearTimeout: timers.clear,
  });
  retryController.start();
  await retryCard.children[0].click();
  assert.equal(retryCard.children[0].textContent, "再試行");
  assert.equal(retryCard.children[0].disabled, false);
  await retryCard.children[0].click();
  assert.equal(retryCalls, 2);
  assert.equal(retryCard.children[0].textContent, "✓ 収集済み");
  retryController.stop();
  controller.stop();
  assert.equal(FakeObserver.instance.disconnected, true);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
