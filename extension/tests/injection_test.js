"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

require(path.join(__dirname, "..", "injection.js"));

class FakeElement {
  constructor() {
    this.attributes = {};
    this.children = [];
    this.style = {};
    this.parentElement = null;
    this.hidden = false;
  }
  setAttribute(name, value) { this.attributes[name] = value; }
  getAttribute(name) { return this.attributes[name] ?? null; }
  appendChild(child) { child.parentElement = this; this.children.push(child); }
}

class FakeButton extends FakeElement {
  constructor() {
    super();
    this.listeners = {};
    this.disabled = false;
  }
  addEventListener(name, listener) { this.listeners[name] = listener; }
  async click() { return this.listeners.click({ preventDefault() {}, stopPropagation() {} }); }
}

class FakeToolbar extends FakeElement {
  constructor(card, count) {
    super();
    this.parentElement = card;
    for (let index = 0; index < count; index += 1) this.appendChild(new FakeButton());
  }
  querySelectorAll(selector) { return selector.includes("button") ? this.children : []; }
}

class FakeSignal extends FakeElement {}

class FakeCard extends FakeElement {
  constructor(name, recognized, options = {}) {
    super();
    this.name = name;
    this.recognized = recognized;
    this.parentElement = options.parentElement || null;
    this.tagName = options.tagName || "DIV";
    this.role = options.role || null;
    this.signals = Array.from({ length: options.signalCount ?? 1 }, () => new FakeSignal());
    this.links = Array.from({ length: options.postCount ?? 1 }, () => ({ parentElement: this }));
    this.link = this.links[0];
    this.times = Array.from({ length: options.timeCount ?? 1 }, () => ({}));
    this.toolbar = new FakeToolbar(this, options.toolbarCount ?? 0);
  }
  getAttribute(name) { return name === "role" ? this.role : super.getAttribute(name); }
  querySelectorAll(selector) {
    if (selector === 'a[href*="/post/"]') return this.links;
    if (selector === "time[datetime]") return this.times;
    if (selector.includes('[dir="auto"]')) return this.signals;
    if (selector.includes("button")) return this.toolbar.children;
    return [];
  }
  querySelector(selector) {
    if (selector.includes("data-sce-pattern-action")) return actionButton(this);
    return this.recognized && selector === "time[datetime]" ? {} : null;
  }
}

class FakeDocument {
  constructor(cards) { this.cards = cards; this.documentElement = {}; }
  querySelectorAll() { return this.cards.filter((card) => card.recognized).map((card) => card.link); }
  createElement(name) {
    if (name === "button") return new FakeButton();
    if (name === "div") return new FakeElement();
    assert.fail(`unexpected element: ${name}`);
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

function actionButton(card) {
  const candidates = [
    ...card.toolbar.children,
    ...card.children.flatMap((child) => child.children || [child]),
  ];
  return candidates.find((item) => item.attributes["data-sce-pattern-action"] === "v1") || null;
}

function actionCounts(cards) { return cards.map((card) => actionButton(card) ? 1 : 0); }

function cardsFromFixture() {
  const html = fs.readFileSync(path.join(__dirname, "fixtures", "injection_surfaces.html"), "utf8");
  assert.equal(html.includes("cookie"), false);
  assert.equal(html.includes("<article"), false, "fixture must reproduce DIV-only cards");
  return [
    new FakeCard("initial-one", html.includes('data-fixture="initial-one"'), { toolbarCount: 3 }),
    new FakeCard("initial-two", html.includes('data-fixture="initial-two"'), { toolbarCount: 2 }),
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
  assert.deepEqual(actionCounts(cards), [1, 1, 0]);
  assert.equal(cards[0].toolbar.children.includes(actionButton(cards[0])), true);
  assert.equal(cards[0].children.length, 0, "reliable toolbar must be preferred");
  assert.equal(cards[1].children[0].attributes["data-sce-pattern-action-fallback"], "v1");
  assert.equal(actionButton(cards[1]).parentElement, cards[1].children[0]);
  const styled = actionButton(cards[0]);
  assert.equal(styled.style.font, "inherit");
  assert.equal(styled.style.fontSize, "12.5px");
  assert.equal(styled.style.borderRadius, "999px");
  assert.equal(styled.style.border, "1px solid currentColor");
  assert.equal(styled.style.backgroundColor, "Canvas");
  assert.equal(styled.style.color, "CanvasText");
  assert.equal(extractionCount, 0, "initial scan must not collect automatically");
  controller.scan();
  assert.deepEqual(actionCounts(cards), [1, 1, 0]);

  const broad = new FakeCard("broad", true, {
    postCount: 2, timeCount: 2, signalCount: 3, toolbarCount: 5,
  });
  const narrowWithoutSignals = new FakeCard("narrow", true, {
    signalCount: 0, tagName: "SPAN", parentElement: broad,
  });
  assert.equal(controller.resolveCardContainer(narrowWithoutSignals.link), null);
  assert.equal(controller.findActionToolbar(broad), broad.toolbar);

  const dynamic = new FakeCard("dynamic", true);
  documentObject.cards.push(dynamic);
  FakeObserver.instance.trigger();
  FakeObserver.instance.trigger();
  assert.equal(timers.size(), 1, "mutation scans must be debounced");
  timers.flush();
  assert.equal(actionCounts([dynamic])[0], 1);
  assert.equal(extractionCount, 0, "dynamic scan must not collect automatically");

  windowObject.location.href = "https://www.threads.com/search?q=two";
  windowObject.dispatch("popstate");
  timers.flush();
  assert.deepEqual(actionCounts(documentObject.cards), [1, 1, 0, 1]);

  const dynamicAction = actionButton(dynamic);
  await Promise.all([dynamicAction.click(), dynamicAction.click()]);
  assert.equal(extractionCount, 1, "concurrent duplicate clicks must collapse");
  assert.equal(observations.length, 1);
  assert.equal(dynamicAction.disabled, true);
  assert.equal(dynamicAction.textContent, "✓ 収集済み");

  const retryCard = new FakeCard("retry", true);
  const retryController = globalThis.SCE_PATTERN_ACTION_INJECTION.createController({
    document: new FakeDocument([retryCard]), window: windowObject, extractor,
    MutationObserver: FakeObserver, onObservation: () => ({ accepted: false, retryable: true }),
    setTimeout: timers.set, clearTimeout: timers.clear,
  });
  retryController.start();
  const retryAction = actionButton(retryCard);
  await retryAction.click();
  assert.equal(retryAction.textContent, "再試行");
  assert.equal(retryAction.disabled, false);
  retryController.stop();
  controller.stop();
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
