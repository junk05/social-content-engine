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
  querySelectorAll(selector) {
    const descendants = this.children.flatMap((child) => [child, ...child.querySelectorAll(selector)]);
    if (selector === "svg") return descendants.filter((child) => child instanceof FakeSvg);
    if (selector === 'a[href*="/post/"]' || selector === "time[datetime]") return [];
    return [];
  }
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

class FakeSvg extends FakeElement {}

class FakeActionOuter extends FakeElement {
  constructor(card) {
    super();
    this.parentElement = card;
    this.style.display = "block";
  }
  querySelectorAll(selector) {
    const row = this.children[0];
    return row ? row.querySelectorAll(selector) : [];
  }
}

class FakeActionRow extends FakeElement {
  constructor(outer, count) {
    super();
    this.parentElement = outer;
    this.style.display = "flex";
    for (let index = 0; index < count; index += 1) this.appendChild(new FakeSvg());
  }
  querySelectorAll(selector) {
    return super.querySelectorAll(selector);
  }
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
    this.links = Array.from({ length: options.postCount ?? 1 }, (_, index) => ({
      parentElement: this,
      getAttribute(name) {
        return name === "href" ? `/@${name}-${index}/post/${this.cardName}` : null;
      },
      cardName: name,
    }));
    this.link = this.links[0];
    this.times = Array.from({ length: options.timeCount ?? 1 }, () => ({}));
    this.actionOuter = new FakeActionOuter(this);
    this.actionRow = new FakeActionRow(this.actionOuter, options.svgCount ?? 0);
    this.actionOuter.appendChild(this.actionRow);
  }
  getAttribute(name) { return name === "role" ? this.role : super.getAttribute(name); }
  querySelectorAll(selector) {
    if (selector === 'a[href*="/post/"]') return this.links;
    if (selector === "time[datetime]") return this.times;
    if (selector.includes('[dir="auto"]')) return this.signals;
    if (selector === "svg") return this.actionRow.querySelectorAll("svg");
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
    getComputedStyle(element) {
      return { display: element.style.display || "block", visibility: "visible",
        position: element.style.position || "static", paddingBlockEnd: "0px" };
    },
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
    ...card.children,
    ...card.actionRow.children,
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
    new FakeCard("initial-one", html.includes('data-fixture="initial-one"'), {
      svgCount: 4, postCount: 2, timeCount: 1,
    }),
    new FakeCard("initial-two", html.includes('data-fixture="initial-two"'), { svgCount: 2 }),
    new FakeCard("non-card", false),
  ];
}

async function main() {
  const cards = cardsFromFixture();
  const documentObject = new FakeDocument(cards);
  const windowObject = fakeWindow();
  const timers = fakeTimers();
  const observations = [];
  const collectedUrls = new Set();
  const collectionState = {
    async isCollected(postUrl) { return collectedUrls.has(postUrl); },
    async markCollected(postUrl) { collectedUrls.add(postUrl); },
  };
  let extractionCount = 0;
  const extractor = {
    recognizeSearchCard(card) { return card.recognized; },
    canonicalPostUrl(value, baseUrl) {
      try {
        const parsed = new URL(value, baseUrl);
        return `https://www.threads.net${parsed.pathname}`;
      } catch (_error) {
        return null;
      }
    },
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
    collectionState,
    setTimeout: timers.set, clearTimeout: timers.clear,
  });

  controller.start();
  assert.deepEqual(actionCounts(cards), [1, 1, 0]);
  assert.equal(cards[0].children.length, 0);
  assert.equal(controller.findActionRow(cards[0]), cards[0].actionRow);
  assert.equal(cards[0].actionOuter.style.display, "block");
  assert.equal(cards[0].actionRow.style.display, "flex");
  assert.equal(controller.findActionRow(cards[1]), null);
  assert.equal(actionButton(cards[0]).parentElement, cards[0].actionRow);
  assert.equal(cards[0].children.some((child) => child.attributes["data-sce-pattern-action-fallback"]), false);
  assert.equal(cards[0].style.position, undefined);
  assert.equal(cards[0].style.paddingBlockEnd, undefined);
  const styled = actionButton(cards[0]);
  assert.equal(styled.style.font, "inherit");
  assert.equal(styled.style.fontSize, "12.5px");
  assert.equal(styled.style.borderRadius, "999px");
  assert.equal(styled.style.border, "1px solid currentColor");
  assert.equal(styled.style.backgroundColor, "Canvas");
  assert.equal(styled.style.color, "CanvasText");
  assert.equal(styled.style.position, "static");
  assert.equal(styled.style.marginInlineStart, "auto");
  assert.equal(styled.style.flexShrink, "0");
  assert.equal(styled.style.alignSelf, "center");
  assert.equal(controller.resolveCardContainer(cards[0].link), cards[0]);

  const removedByRerender = actionButton(cards[0]);
  cards[0].actionRow.children = cards[0].actionRow.children.filter((child) => child !== removedByRerender);
  controller.scan();
  assert.equal(actionCounts(cards)[0], 1, "a Threads rerender must allow safe reinjection when the button is gone");

  const nestedActions = new FakeCard("nested-actions", true, { svgCount: 0 });
  let nestedParent = nestedActions.actionRow;
  for (let depth = 0; depth < 4; depth += 1) {
    const wrapper = new FakeElement();
    nestedParent.appendChild(wrapper);
    nestedParent = wrapper;
  }
  for (let index = 0; index < 4; index += 1) nestedParent.appendChild(new FakeSvg());
  assert.equal(
    controller.findActionRow(nestedActions), nestedActions.actionRow,
    "a nested Threads icon must still resolve to its flex reaction row",
  );
  const fallback = actionButton(cards[1]);
  assert.equal(fallback.parentElement, cards[1]);
  assert.equal(fallback.style.position, "absolute");
  assert.equal(fallback.style.insetInlineEnd, "8px");
  assert.equal(fallback.style.insetBlockEnd, "8px");
  assert.equal(cards[1].style.position, "relative");
  assert.equal(cards[1].style.paddingBlockEnd, "40px");
  assert.equal(extractionCount, 0, "initial scan must not collect automatically");
  controller.scan();
  assert.deepEqual(actionCounts(cards), [1, 1, 0]);

  const broad = new FakeCard("broad", true, {
    postCount: 2, timeCount: 2, signalCount: 3, svgCount: 7,
  });
  assert.equal(controller.findActionRow(broad), null, "broad groups with over six SVGs are rejected");
  const fullCard = new FakeCard("full-card", true, {
    signalCount: 4, tagName: "DIV", parentElement: broad,
  });
  const headerRow = new FakeCard("header-row", true, {
    signalCount: 1, tagName: "DIV", parentElement: fullCard,
  });
  assert.equal(
    controller.resolveCardContainer(headerRow.link), fullCard,
    "resolver must choose the outermost bounded card before the multi-post parent",
  );
  documentObject.cards.push(headerRow);
  controller.scan();
  assert.equal(actionButton(fullCard).parentElement, fullCard);
  assert.equal(headerRow.children.length, 0, "absolute action must not enter or shift the header row");
  assert.equal(actionButton(fullCard).style.position, "absolute");
  const narrowWithoutSignals = new FakeCard("narrow", true, {
    signalCount: 0, tagName: "SPAN", parentElement: broad,
  });
  assert.equal(controller.resolveCardContainer(narrowWithoutSignals.link), null);

  const tooBroad = new FakeCard("too-broad", true, {
    postCount: 3, timeCount: 1, signalCount: 5,
  });
  let deep = tooBroad;
  for (let depth = 0; depth < 10; depth += 1) {
    deep = new FakeCard(`depth-${depth}`, true, { parentElement: deep, signalCount: depth + 1 });
  }
  assert.notEqual(
    controller.resolveCardContainer(deep.link), null,
    "resolver must retain bounded cards across live-depth ancestry",
  );

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
  assert.deepEqual(actionCounts(documentObject.cards), [1, 1, 0, 0, 1]);

  const dynamicAction = actionButton(dynamic);
  await Promise.all([dynamicAction.click(), dynamicAction.click()]);
  assert.equal(extractionCount, 1, "concurrent duplicate clicks must collapse");
  assert.equal(observations.length, 1);
  assert.equal(dynamicAction.disabled, true);
  assert.equal(dynamicAction.textContent, "✓ 収集済み");
  assert.equal(collectedUrls.size, 1, "only the canonical selected URL is persisted locally");

  const restoredCard = new FakeCard("dynamic", true);
  const restoredController = globalThis.SCE_PATTERN_ACTION_INJECTION.createController({
    document: new FakeDocument([restoredCard]), window: windowObject, extractor,
    MutationObserver: FakeObserver, onObservation: () => ({ accepted: true }),
    collectionState, setTimeout: timers.set, clearTimeout: timers.clear,
  });
  restoredController.start();
  await Promise.resolve();
  assert.equal(actionButton(restoredCard).textContent, "✓ 収集済み");
  assert.equal(actionButton(restoredCard).disabled, true);
  restoredController.stop();

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
