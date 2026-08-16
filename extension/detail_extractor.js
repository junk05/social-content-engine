"use strict";

// Versioned, read-only extraction for an already open Threads post-detail page.
// Navigation, batching, DOM observation, and transport are intentionally absent.
(function exposeThreadsPostDetailExtractor(scope) {
  const VERSION = "threads_post_detail_extractor_v1";
  const SURFACE = "threads_post_detail";
  const COUNTERS = Object.freeze({
    view_count: ["表示", "view"], like_count: ["いいね", "like"],
    reply_count: ["返信", "reply"], repost_count: ["再投稿", "repost"],
    quote_count: ["引用", "quote"], share_count: ["シェア", "share"],
  });

  function canonicalPostUrl(value, baseUrl) {
    let parsed;
    try { parsed = new URL(value, baseUrl); } catch (_error) { return null; }
    const host = parsed.hostname.toLowerCase();
    if (parsed.protocol !== "https:" || !["threads.net", "www.threads.net", "threads.com", "www.threads.com"].includes(host)) return null;
    const match = parsed.pathname.match(/^\/@([A-Za-z0-9._-]+)\/post\/([A-Za-z0-9._-]+)\/?$/);
    if (!match) return null;
    return "https://www.threads.net/@" + match[1].toLowerCase() + "/post/" + match[2];
  }

  function isVisible(element) { return !element.hidden && element.getAttribute("aria-hidden") !== "true"; }
  function cleanText(value) {
    if (typeof value !== "string") return null;
    const cleaned = value.replace(/\s+/g, " ").trim();
    return cleaned || null;
  }
  function renderedText(element) {
    return cleanText(typeof element.innerText === "string" ? element.innerText : null);
  }
  function exactNonnegativeInteger(label) {
    if (typeof label !== "string") return null;
    if (/[0-9][0-9,.]*\s*(?:k|m|b|万|千|億)/i.test(label)) return null;
    const matches = label.match(/[0-9][0-9,]*/g);
    if (!matches || matches.length !== 1) return null;
    const token = matches[0];
    if (!/^(?:0|[1-9][0-9]{0,2}(?:,[0-9]{3})*|[1-9][0-9]*)$/.test(token)) return null;
    const value = Number(token.replaceAll(",", ""));
    return Number.isSafeInteger(value) ? value : null;
  }
  function findPermalink(root, pageUrl, expectedCanonical = null) {
    for (const link of root.querySelectorAll('a[href*="/post/"]')) {
      if (!isVisible(link)) continue;
      const canonical = canonicalPostUrl(link.getAttribute("href"), pageUrl);
      if (canonical && (!expectedCanonical || canonical === expectedCanonical)) {
        return { link, canonical };
      }
    }
    return null;
  }
  function recognizePostDetail(root, pageUrl) {
    if (!root || typeof root.querySelectorAll !== "function" || typeof root.querySelector !== "function") return false;
    const canonicalPage = canonicalPostUrl(pageUrl, pageUrl);
    const permalink = findPermalink(
      root, pageUrl || "https://www.threads.net/", canonicalPage
    );
    const time = root.querySelector("time[datetime]");
    return Boolean(canonicalPage && permalink && canonicalPage === permalink.canonical && time && isVisible(time));
  }
  function profileValues(root, canonicalUrl) {
    const username = canonicalUrl.match(/\/@([^/]+)\/post\//)[1];
    let authorName = null;
    for (const link of root.querySelectorAll('a[href^="/@"]')) {
      if (!isVisible(link)) continue;
      const href = link.getAttribute("href") || "";
      if (href.split(/[?#]/)[0].toLowerCase() !== "/@" + username) continue;
      const candidate = renderedText(link);
      if (candidate && candidate.toLowerCase() !== username) authorName = candidate;
      break;
    }
    return { username, authorName };
  }
  function visibleCounters(root) {
    const counters = {};
    for (const name of Object.keys(COUNTERS)) counters[name] = null;
    for (const element of root.querySelectorAll("[aria-label]")) {
      if (!isVisible(element)) continue;
      const label = element.getAttribute("aria-label") || "";
      const lower = label.toLowerCase();
      for (const [name, markers] of Object.entries(COUNTERS)) {
        if (!markers.some((marker) => lower.includes(marker))) continue;
        const value = exactNonnegativeInteger(label);
        if (value !== null) counters[name] = value;
      }
    }
    return counters;
  }
  function visiblePostText(root, excludedValues) {
    const excluded = new Set(excludedValues.filter(Boolean).map((value) => value.toLowerCase()));
    for (const selector of ['[data-testid="post-text"]', '[dir="auto"]']) {
      for (const candidate of root.querySelectorAll(selector)) {
        if (!isVisible(candidate)) continue;
        if (candidate.closest('a[href^="/@"], a[href*="/post/"], time, button, [role="button"]')) continue;
        const value = renderedText(candidate);
        if (value && !excluded.has(value.toLowerCase())) return value;
      }
    }
    return null;
  }
  function mediaValues(root) {
    const hasVideo = Array.from(root.querySelectorAll("video")).some(isVisible);
    const hasImage = Array.from(root.querySelectorAll('img[alt]:not([alt=""])')).some(isVisible);
    if (hasImage && hasVideo) return { mediaType: "CAROUSEL", hasImage: true, hasVideo: true };
    if (hasVideo) return { mediaType: "VIDEO", hasImage: null, hasVideo: true };
    if (hasImage) return { mediaType: "IMAGE", hasImage: true, hasVideo: null };
    return { mediaType: null, hasImage: null, hasVideo: null };
  }
  function observationField(field, value, observedAt) {
    return { field, value, surface: SURFACE, observed_at: observedAt, extractor_version: VERSION };
  }
  function canonicalJson(value) {
    if (Array.isArray(value)) return "[" + value.map(canonicalJson).join(",") + "]";
    if (value && typeof value === "object") {
      return "{" + Object.keys(value).sort().map((key) => JSON.stringify(key) + ":" + canonicalJson(value[key])).join(",") + "}";
    }
    return JSON.stringify(value);
  }
  async function sha256(value) {
    const bytes = new TextEncoder().encode(canonicalJson(value));
    const digest = await crypto.subtle.digest("SHA-256", bytes);
    return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
  }
  async function extractPostDetail(root, context = {}) {
    const pageUrl = typeof context.pageUrl === "string" ? context.pageUrl : null;
    if (!recognizePostDetail(root, pageUrl)) return null;
    const collectedAt = context.collectedAt || new Date().toISOString();
    const post = findPermalink(
      root, pageUrl, canonicalPostUrl(pageUrl, pageUrl)
    );
    const time = root.querySelector("time[datetime]");
    const timestamp = cleanText(time.getAttribute("datetime"));
    if (!post || !timestamp) return null;
    const profile = profileValues(root, post.canonical);
    const counters = visibleCounters(root);
    const counterLabels = Array.from(root.querySelectorAll("[aria-label]"), (element) => isVisible(element) ? cleanText(element.getAttribute("aria-label")) : null);
    const text = visiblePostText(root, [profile.authorName, profile.username, timestamp, ...counterLabels]);
    const media = mediaValues(root);
    const observed = [];
    for (const [field, value] of [
      ["author_name", profile.authorName], ["username", profile.username], ["text", text],
      ["timestamp", timestamp], ["media_type", media.mediaType], ["has_image", media.hasImage], ["has_video", media.hasVideo],
    ]) if (value !== null) observed.push(observationField(field, value, collectedAt));
    for (const [name, value] of Object.entries(counters)) if (value !== null) observed.push(observationField("public_counters." + name, value, collectedAt));
    const observation = {
      schema_version: 1, observation_type: "POST_DETAIL", source: "threads",
      post_url: post.canonical, source_post_id: null,
      author_name: profile.authorName, username: profile.username, text, timestamp,
      public_counters: counters, media_type: media.mediaType, has_image: media.hasImage, has_video: media.hasVideo,
      collection_context: { surface: SURFACE, page_url: post.canonical, query: null, position: null },
      observed_fields: observed, collected_at: collectedAt, extractor_version: VERSION,
    };
    observation.payload_sha256 = await sha256(observation);
    return observation;
  }
  scope.SCE_THREADS_POST_DETAIL_EXTRACTOR = Object.freeze({
    version: VERSION, canonicalPostUrl, exactNonnegativeInteger, recognizePostDetail, extractPostDetail,
  });
})(globalThis);
