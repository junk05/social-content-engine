"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

if (!globalThis.crypto) globalThis.crypto = require("node:crypto").webcrypto;
require(path.join(__dirname, "..", "extractor.js"));

class Element {
  constructor(attributes = {}, textContent = "", excluded = false) {
    this.attributes = attributes;
    this.textContent = textContent;
    this.hidden = false;
    this.excluded = excluded;
  }
  getAttribute(name) { return this.attributes[name] ?? null; }
  closest() { return this.excluded ? this : null; }
}

function stripTags(value) {
  return value.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
}

function fixtureCard(name) {
  const html = fs.readFileSync(path.join(__dirname, "fixtures", name), "utf8");
  const anchors = Array.from(html.matchAll(/<a\s+href="([^"]+)"[^>]*>([\s\S]*?)<\/a>/g),
    (match) => new Element({ href: match[1] }, stripTags(match[2])));
  const labels = Array.from(html.matchAll(/<[^>]+aria-label="([^"]+)"[^>]*>/g),
    (match) => new Element({ "aria-label": match[1] }));
  const candidates = Array.from(
    html.matchAll(/<(div|span)\s+([^>]*(?:dir="auto"|data-testid="post-text")[^>]*)>([\s\S]*?)<\/\1>/g),
    (match) => {
      const before = html.slice(0, match.index);
      const insideProfile = before.lastIndexOf("<a ") > before.lastIndexOf("</a>");
      const insideButton = before.lastIndexOf("<button") > before.lastIndexOf("</button>");
      const attributes = {};
      if (match[2].includes('aria-hidden="true"')) attributes["aria-hidden"] = "true";
      if (match[2].includes('data-testid="post-text"')) attributes["data-testid"] = "post-text";
      if (match[2].includes('dir="auto"')) attributes.dir = "auto";
      return new Element(attributes, stripTags(match[3]), insideProfile || insideButton);
    },
  );
  const timeMatch = html.match(/<time\s+datetime="([^"]+)"/);
  return {
    html,
    querySelectorAll(selector) {
      if (selector === 'a[href*="/post/"]') return anchors.filter((item) => item.getAttribute("href").includes("/post/"));
      if (selector === 'a[href^="/@"]') return anchors.filter((item) => item.getAttribute("href").startsWith("/@"));
      if (selector === "[aria-label]") return labels;
      if (selector === '[data-testid="post-text"]') return candidates.filter((item) => item.getAttribute("data-testid") === "post-text");
      if (selector === '[dir="auto"]') return candidates.filter((item) => item.getAttribute("dir") === "auto");
      return [];
    },
    querySelector(selector) {
      if (selector === "time[datetime]") return timeMatch ? new Element({ datetime: timeMatch[1] }) : null;
      if (selector === "video") return html.includes("<video") ? new Element() : null;
      if (selector.startsWith("img[alt]")) return /<img[^>]+alt="[^"]+"/.test(html) ? new Element() : null;
      return null;
    },
  };
}

async function main() {
  const extractor = globalThis.SCE_THREADS_SEARCH_CARD_EXTRACTOR;
  assert.equal(extractor.version, "threads_search_card_extractor_v1");
  const context = {
    collectedAt: "2026-08-16T03:04:05.000Z",
    pageUrl: "https://www.threads.com/search?q=sanitized",
    query: "sanitized",
    position: 2,
  };
  const complete = await extractor.extractSearchCard(fixtureCard("search_card_complete.html"), context);
  assert.equal(complete.post_url, "https://www.threads.net/@sample.user/post/AbC_123");
  assert.equal(complete.source_post_id, null);
  assert.equal(complete.author_name, "Sample Author");
  assert.equal(complete.username, "sample.user");
  assert.equal(complete.text, "Sanitized public post text.");
  assert.deepEqual(complete.public_counters, {
    view_count: null, like_count: 1234, reply_count: 0,
    repost_count: 7, quote_count: null, share_count: null,
  });
  assert.equal(complete.media_type, "IMAGE");
  assert.equal(complete.has_image, true);
  assert.equal(complete.has_video, null);
  assert.equal(complete.collection_context.surface, "threads_search_card");
  assert.equal(complete.observed_fields.some((item) => item.value === null), false);
  assert.match(complete.payload_sha256, /^[0-9a-f]{64}$/);
  assert.equal(JSON.stringify(complete).includes("html"), false);
  assert.equal(JSON.stringify(complete).includes("dom"), false);

  const repeated = await extractor.extractSearchCard(fixtureCard("search_card_complete.html"), context);
  assert.equal(repeated.payload_sha256, complete.payload_sha256);

  const missing = await extractor.extractSearchCard(fixtureCard("search_card_missing.html"), context);
  assert.equal(missing.source_post_id, null);
  assert.equal(missing.author_name, null);
  assert.equal(missing.text, null);
  assert.equal(missing.media_type, null);
  assert.deepEqual(Object.values(missing.public_counters), [null, null, null, null, null, null]);
  assert.equal(missing.observed_fields.some((item) => item.field === "text"), false);

  const noText = await extractor.extractSearchCard(fixtureCard("search_card_no_text.html"), context);
  assert.equal(noText.author_name, "Only Profile");
  assert.equal(noText.public_counters.like_count, 12);
  assert.equal(noText.text, null);
  assert.equal(noText.observed_fields.some((item) => item.field === "text"), false);

  assert.equal(extractor.exactNonnegativeInteger("Like 1.2K"), null);
  assert.equal(extractor.canonicalPostUrl("javascript:alert(1)", context.pageUrl), null);
  assert.equal(await extractor.extractSearchCard({ querySelectorAll() { return []; } }, context), null);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
