"use strict";

// Versioned extraction only. Button injection, DOM observation, and transport
// intentionally belong to M3-006 and are not performed by this module.
(function exposeThreadsSearchCardExtractor(scope) {
  const VERSION = "threads_search_card_extractor_v1";
  const SURFACE = "threads_search_card";
  const COUNTERS = Object.freeze({
    view_count: ["表示", "view"],
    like_count: ["いいね", "like"],
    reply_count: ["返信", "reply"],
    repost_count: ["再投稿", "repost"],
    quote_count: ["引用", "quote"],
    share_count: ["シェア", "share"],
  });

  function canonicalPostUrl(value, baseUrl) {
    let parsed;
    try {
      parsed = new URL(value, baseUrl);
    } catch (_error) {
      return null;
    }
    if (parsed.protocol !== "https:" || !["threads.net", "www.threads.net", "threads.com", "www.threads.com"].includes(parsed.hostname.toLowerCase())) {
      return null;
    }
    const match = parsed.pathname.match(/^\/@([A-Za-z0-9._-]+)\/post\/([A-Za-z0-9._-]+)\/?$/);
    if (!match) return null;
    return `https://www.threads.net/@${match[1].toLowerCase()}/post/${match[2]}`;
  }

  function exactNonnegativeInteger(label) {
    if (typeof label !== "string") return null;
    const matches = label.match(/[0-9][0-9,]*/g);
    if (!matches || matches.length !== 1) return null;
    const digits = matches[0].replaceAll(",", "");
    return /^[0-9]+$/.test(digits) ? Number(digits) : null;
  }

  function cleanText(value) {
    if (typeof value !== "string") return null;
    const cleaned = value.replace(/\s+/g, " ").trim();
    return cleaned || null;
  }

  function findPostLink(card, pageUrl) {
    for (const link of card.querySelectorAll('a[href*="/post/"]')) {
      const canonical = canonicalPostUrl(link.getAttribute("href"), pageUrl);
      if (canonical) return { link, canonical };
    }
    return null;
  }

  function profileValues(card, canonicalUrl) {
    const username = canonicalUrl.match(/\/@([^/]+)\/post\//)[1];
    let authorName = null;
    for (const link of card.querySelectorAll('a[href^="/@"]')) {
      const href = link.getAttribute("href") || "";
      if (href.split(/[?#]/)[0].toLowerCase() === `/@${username}`) {
        const candidate = cleanText(link.textContent);
        if (candidate && candidate.toLowerCase() !== username) authorName = candidate;
        break;
      }
    }
    return { username, authorName };
  }

  function visibleCounters(card) {
    const counters = {};
    for (const name of Object.keys(COUNTERS)) counters[name] = null;
    for (const element of card.querySelectorAll("[aria-label]")) {
      const label = element.getAttribute("aria-label") || "";
      const lower = label.toLowerCase();
      for (const [name, words] of Object.entries(COUNTERS)) {
        if (words.some((word) => lower.includes(word))) {
          const value = exactNonnegativeInteger(label);
          if (value !== null) counters[name] = value;
        }
      }
    }
    return counters;
  }

  function mediaValues(card) {
    const hasVideo = Boolean(card.querySelector("video"));
    const hasImage = Boolean(card.querySelector('img[alt]:not([alt=""])'));
    if (hasImage && hasVideo) return { mediaType: "CAROUSEL", hasImage: true, hasVideo: true };
    if (hasVideo) return { mediaType: "VIDEO", hasImage: null, hasVideo: true };
    if (hasImage) return { mediaType: "IMAGE", hasImage: true, hasVideo: null };
    return { mediaType: null, hasImage: null, hasVideo: null };
  }

  function visiblePostText(card, excludedValues) {
    const selectors = ['[data-testid="post-text"]', '[dir="auto"]'];
    const excluded = new Set(excludedValues.filter(Boolean).map((value) => value.toLowerCase()));
    for (const selector of selectors) {
      for (const candidate of card.querySelectorAll(selector)) {
        if (candidate.hidden || candidate.getAttribute("aria-hidden") === "true") continue;
        if (candidate.closest('a[href^="/@"], a[href*="/post/"], time, button, [role="button"]')) continue;
        const value = cleanText(candidate.textContent);
        if (!value || excluded.has(value.toLowerCase())) continue;
        return value;
      }
    }
    return null;
  }

  function observationField(field, value, observedAt) {
    return { field, value, surface: SURFACE, observed_at: observedAt, extractor_version: VERSION };
  }

  function canonicalJson(value) {
    if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
    if (value && typeof value === "object") {
      return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${canonicalJson(value[key])}`).join(",")}}`;
    }
    return JSON.stringify(value);
  }

  async function sha256(value) {
    const bytes = new TextEncoder().encode(canonicalJson(value));
    const digest = await crypto.subtle.digest("SHA-256", bytes);
    return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
  }

  async function extractSearchCard(card, context = {}) {
    if (!card || typeof card.querySelectorAll !== "function" || typeof card.querySelector !== "function") return null;
    const collectedAt = context.collectedAt || new Date().toISOString();
    const pageUrl = typeof context.pageUrl === "string" ? context.pageUrl : null;
    const post = findPostLink(card, pageUrl || "https://www.threads.net/");
    const time = card.querySelector("time[datetime]");
    if (!post || !time) return null;
    const timestamp = cleanText(time.getAttribute("datetime"));
    if (!timestamp) return null;
    const profile = profileValues(card, post.canonical);
    const counters = visibleCounters(card);
    const counterLabels = Array.from(card.querySelectorAll("[aria-label]"), (element) => cleanText(element.getAttribute("aria-label")));
    const text = visiblePostText(card, [profile.authorName, profile.username, timestamp, ...counterLabels]);
    const media = mediaValues(card);
    const observed = [];
    for (const [field, value] of [
      ["author_name", profile.authorName], ["username", profile.username], ["text", text],
      ["timestamp", timestamp], ["media_type", media.mediaType], ["has_image", media.hasImage],
      ["has_video", media.hasVideo],
    ]) if (value !== null) observed.push(observationField(field, value, collectedAt));
    for (const [name, value] of Object.entries(counters)) {
      if (value !== null) observed.push(observationField(`public_counters.${name}`, value, collectedAt));
    }
    const observation = {
      schema_version: 1, observation_type: "SEARCH_CARD", source: "threads",
      post_url: post.canonical, source_post_id: null,
      author_name: profile.authorName, username: profile.username, text, timestamp,
      public_counters: counters, media_type: media.mediaType,
      has_image: media.hasImage, has_video: media.hasVideo,
      collection_context: {
        surface: SURFACE, page_url: pageUrl,
        query: typeof context.query === "string" ? context.query : null,
        position: Number.isInteger(context.position) && context.position >= 0 ? context.position : null,
      },
      observed_fields: observed, collected_at: collectedAt, extractor_version: VERSION,
    };
    observation.payload_sha256 = await sha256(observation);
    return observation;
  }

  scope.SCE_THREADS_SEARCH_CARD_EXTRACTOR = Object.freeze({
    version: VERSION, canonicalPostUrl, exactNonnegativeInteger, extractSearchCard,
  });
})(globalThis);
