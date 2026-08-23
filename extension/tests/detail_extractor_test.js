"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

if (!globalThis.crypto) globalThis.crypto = require("node:crypto").webcrypto;
require(path.join(__dirname, "..", "detail_extractor.js"));

class Element {
  constructor(attributes = {}, textContent = "", excluded = false) {
    this.attributes = attributes;
    this.textContent = textContent;
    this.innerText = textContent;
    this.hidden = Object.hasOwn(attributes, "hidden");
    this.excluded = excluded;
  }
  getAttribute(name) { return this.attributes[name] ?? null; }
  closest(selector) {
    if (this.excluded) return this;
    const href = this.getAttribute("href") || "";
    const topic = this.getAttribute("data-topic-tag") !== null
      || this.getAttribute("data-testid") === "topic-tag"
      || href.includes("serp_type=tags") || href.includes("serp_type=tag")
      || href.includes("/topic/") || href.includes("/t/");
    return topic && selector.includes("topic") ? this : null;
  }
  querySelector(selector) {
    return selector === "time[datetime]" && this.containsTime ? {} : null;
  }
}

function attributes(value) {
  const result = {};
  for (const match of value.matchAll(/([\w-]+)(?:="([^"]*)")?/g)) result[match[1]] = match[2] ?? "";
  return result;
}

function stripTags(value) {
  return value.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
}

function stripHiddenAndTags(value) {
  return stripTags(value.replace(/<[^>]+aria-hidden="true"[^>]*>[\s\S]*?<\/[^>]+>/g, " "));
}

function fixturePage(name) {
  const html = fs.readFileSync(path.join(__dirname, "fixtures", name), "utf8");
  const anchors = Array.from(html.matchAll(/<a\s+([^>]*)>([\s\S]*?)<\/a>/g),
    (match) => {
      const element = new Element(attributes(match[1]), stripTags(match[2]));
      element.containsTime = /<time\s+[^>]*datetime=/.test(match[2]);
      return element;
    });
  const labelled = Array.from(html.matchAll(/<[^>]+aria-label="([^"]+)"[^>]*>/g),
    (match) => new Element(attributes(match[0])));
  const candidates = Array.from(
    html.matchAll(/<(div|span)\s+([^>]*(?:dir="auto"|data-testid="post-text")[^>]*)>([\s\S]*?)<\/\1>/g),
    (match) => new Element(attributes(match[2]), stripHiddenAndTags(match[3])),
  );
  const sequenceIndicators = Array.from(
    html.matchAll(/<(div|span)\s+([^>]*(?:x1rg5ohu|thread-sequence-indicator)[^>]*)>([^<]*)<\/\1>/g),
    (match) => new Element(attributes(match[2]), stripTags(match[3])),
  );
  const displayLabels = Array.from(
    html.matchAll(/<(?:div|span)(?:\s+[^>]*)?>([^<]+)<\/(?:div|span)>/g),
    (match) => new Element({}, stripTags(match[1])),
  );
  const dialogs = Array.from(html.matchAll(/<(?:div|section)\s+([^>]*role="dialog"[^>]*)>([\s\S]*?)<\/(?:div|section)>/g),
    (match) => new Element(attributes(match[1]), stripTags(match[2])));
  for (const dialog of dialogs) {
    dialog.querySelectorAll = (selector) => selector === "span, div" ? [dialog] : [];
  }
  const timeMatch = html.match(/<time\s+([^>]*)>/);
  const media = Array.from(html.matchAll(/<(img|video)\s*([^>]*)>/g),
    (match) => ({ tag: match[1], element: new Element(attributes(match[2])) }));
  return {
    querySelectorAll(selector) {
      if (selector === 'a[href*="/post/"]') return anchors.filter((item) => (item.getAttribute("href") || "").includes("/post/"));
      if (selector === 'a[href^="/@"]') return anchors.filter((item) => (item.getAttribute("href") || "").startsWith("/@"));
      if (selector === "[aria-label]") return labelled;
      if (selector === '[data-testid="post-text"]') return candidates.filter((item) => item.getAttribute("data-testid") === "post-text");
      if (selector === '[dir="auto"]') return candidates.filter((item) => item.getAttribute("dir") === "auto");
      if (selector.includes('[data-testid="topic-tag"]')) return candidates.filter((item) => (
        item.getAttribute("data-testid") === "topic-tag"
        || item.getAttribute("data-topic-tag") !== null
      ));
      if (selector.includes("div.x1rg5ohu")) return sequenceIndicators;
      if (selector === "span, div") return displayLabels;
      if (selector === '[role="dialog"], [aria-modal="true"]') return dialogs;
      if (selector === "video") return media.filter((item) => item.tag === "video").map((item) => item.element);
      if (selector === 'img[alt]:not([alt=""])') return media.filter((item) => item.tag === "img" && item.element.getAttribute("alt")).map((item) => item.element);
      return [];
    },
    querySelector(selector) {
      if (selector === "time[datetime]") return timeMatch ? new Element(attributes(timeMatch[1])) : null;
      return null;
    },
  };
}

async function main() {
  const extractor = globalThis.SCE_THREADS_POST_DETAIL_EXTRACTOR;
  const source = fs.readFileSync(path.join(__dirname, "..", "detail_extractor.js"), "utf8");
  assert.match(source, /visibleCounters\(postRoot\)/);
  assert.match(source, /visiblePostText\(\s*postRoot,/);
  assert.match(source, /visibleActivityDialogViewCount\(root\)/,
    "root metrics and text are card-scoped while exact Activity views are dialog-scoped");
  assert.equal(extractor.version, "threads_post_detail_extractor_v11");
  const context = {
    collectedAt: "2026-08-16T03:04:05.000Z",
    pageUrl: "https://www.threads.com/@Sample.User/post/AbC_123?source=fixture",
  };
  const page = fixturePage("post_detail_complete.html");
  assert.equal(extractor.recognizePostDetail(page, context.pageUrl), true);
  assert.deepEqual(extractor.postDetailReadiness(page, context.pageUrl), {
    canonicalPage: true, permalinkFound: true, postRootFound: true, timestampFound: true,
  });
  const nodes = extractor.extractVisibleThreadNodes(page, context.pageUrl);
  assert.deepEqual(nodes.map((node) => node.post_url), [
    "https://www.threads.net/@sample.user/post/AbC_123",
    "https://www.threads.net/@sample.user/post/SelfReply1",
    "https://www.threads.net/@sample.user/post/SelfReply2",
    "https://www.threads.net/@sample.user/post/SelfReply3",
  ], "the root-author chain stops at the first other-author conversation branch");
  assert.deepEqual(nodes.map((node) => node.sequence_position), [0, 1, 2, 3]);
  assert.deepEqual(nodes.map((node) => node.reply_to_post_url), [null, null, null, null],
    "reply-to edges remain unknown when the visible DOM does not expose them");
  assert.deepEqual(nodes.map((node) => node.same_author_as_root), [true, true, true, true]);
  assert.deepEqual(nodes.map((node) => node.relationship_evidence), [
    "ROOT_DETAIL_PAGE",
    "DOM_CONTIGUOUS_ROOT_AUTHOR_CHAIN",
    "DOM_CONTIGUOUS_ROOT_AUTHOR_CHAIN",
    "DOM_CONTIGUOUS_ROOT_AUTHOR_CHAIN",
  ]);
  const diagnostic = extractor.diagnoseVisibleThread(page, context.pageUrl);
  assert.equal(diagnostic.diagnostic_version, "thread_candidate_diagnostic_v1");
  assert.equal(diagnostic.visible_post_nodes, 8);
  assert.equal(diagnostic.root_nodes, 1);
  assert.equal(diagnostic.direct_root_author_candidates, 3);
  assert.equal(diagnostic.other_author_candidates, 2);
  assert.equal(diagnostic.root_author_after_other_boundary, 2);
  assert.equal(diagnostic.root_author_replies_under_other_author, "NOT_OBSERVED");
  assert.equal(diagnostic.final_eligible_nodes, 4);
  assert.deepEqual(diagnostic.exclusion_reasons, {
    OTHER_AUTHOR_BOUNDARY: 2,
    ROOT_AUTHOR_AFTER_OTHER_AUTHOR_BOUNDARY: 2,
  });
  assert.equal(JSON.stringify(diagnostic).includes("sample.user"), false,
    "live author identity is absent from the diagnostic");
  assert.equal(JSON.stringify(diagnostic).includes("SelfReply"), false,
    "live URLs and post identifiers are absent from the diagnostic");
  const complete = await extractor.extractPostDetail(page, context);
  assert.equal(complete.observation_type, "POST_DETAIL");
  assert.deepEqual(Object.keys(complete).sort(), [
    "author_name", "collected_at", "collection_context", "extractor_version",
    "has_image", "has_video", "media_type", "metric_observation_statuses",
    "observation_type", "observed_fields",
    "payload_sha256", "post_url", "public_counters", "raw_sequence_indicator",
    "schema_version", "source", "source_post_id", "text", "thread_position",
    "thread_total", "timestamp", "topic_tags", "username",
  ]);
  assert.equal(complete.post_url, "https://www.threads.net/@sample.user/post/AbC_123");
  assert.equal(complete.source_post_id, null);
  assert.equal(complete.author_name, "Sample Author");
  assert.equal(complete.username, "sample.user");
  assert.equal(complete.text, "Sanitized detail post text.");
  assert.deepEqual(complete.topic_tags, ["Fixture Topic"]);
  assert.equal(complete.raw_sequence_indicator, null);
  assert.deepEqual(complete.public_counters, {
    view_count: 0, like_count: 1234, reply_count: 2,
    repost_count: null, quote_count: null, share_count: 0,
  });
  assert.deepEqual(complete.metric_observation_statuses, {
    view_count: "OBSERVED", like_count: "OBSERVED", reply_count: "OBSERVED",
    repost_count: "NOT_OBSERVED", quote_count: "NOT_OBSERVED",
    share_count: "OBSERVED",
  });
  assert.equal(complete.media_type, "IMAGE");
  assert.equal(complete.collection_context.surface, "threads_post_detail");
  assert.equal(complete.collection_context.page_url, complete.post_url);
  assert.equal(complete.observed_fields.some((item) => item.value === null), false);
  assert.equal(complete.observed_fields.find((item) => item.field === "public_counters.view_count").value, 0);
  assert.equal(complete.observed_fields.every((item) => item.surface === "threads_post_detail"), true);
  assert.equal(complete.observed_fields.every((item) => item.extractor_version === extractor.version), true);
  assert.match(complete.payload_sha256, /^[0-9a-f]{64}$/);
  const selfReplyDetails = await extractor.extractVisibleThreadDetails(
    page, context.pageUrl, context.collectedAt,
  );
  assert.deepEqual(selfReplyDetails.map((item) => item.post_url), [
    "https://www.threads.net/@sample.user/post/SelfReply1",
    "https://www.threads.net/@sample.user/post/SelfReply2",
    "https://www.threads.net/@sample.user/post/SelfReply3",
  ]);
  assert.equal(selfReplyDetails.every((item) => item.observation_type === "POST_DETAIL"), true);
  assert.equal(selfReplyDetails.every((item) => item.text !== null), true);
  assert.equal(selfReplyDetails.every((item) => item.topic_tags[0] === "Fixture Topic"), true,
    "self-reply detail observations reuse the same body/topic separation");
  assert.equal(selfReplyDetails.every((item) => item.approximate_views === undefined), true,
    "self replies never inherit root-level rounded Views");
  assert.equal(selfReplyDetails.every((item) => item.display_views === undefined), true,
    "self replies never inherit root-level integer Views");
  const serialized = JSON.stringify(complete).toLowerCase();
  for (const forbidden of ["<main", "outerhtml", "cookie", "password", "access_token"]) assert.equal(serialized.includes(forbidden), false);

  const replay = await extractor.extractPostDetail(page, context);
  assert.equal(replay.payload_sha256, complete.payload_sha256);

  const missingContext = {
    collectedAt: context.collectedAt,
    pageUrl: "https://www.threads.net/@sample.user/post/MissingView",
  };
  const missing = await extractor.extractPostDetail(fixturePage("post_detail_missing_view.html"), missingContext);
  assert.equal(missing.public_counters.view_count, null);
  assert.equal(missing.public_counters.like_count, 0);
  assert.deepEqual(missing.approximate_views, {
    display: "表示6.4万回", normalized_approx: 64000, precision: "ROUNDED",
    source: "POST_DETAIL_PAGE", view_band: "10K_100K",
    observed_at: context.collectedAt, extractor_version: extractor.version,
    normalizer_version: "rounded-views-normalizer-v1",
  });
  assert.equal(missing.metric_observation_statuses.view_count, "NOT_OBSERVED");
  assert.equal(missing.metric_observation_statuses.like_count, "OBSERVED");
  assert.equal(missing.observed_fields.some((item) => item.field === "public_counters.view_count"), false);
  assert.equal(missing.observed_fields.find((item) => item.field === "public_counters.like_count").value, 0);

  const tagged = await extractor.extractPostDetail(
    fixturePage("post_detail_topic_tag.html"),
    { ...missingContext, pageUrl: "https://www.threads.net/@sample.user/post/Tagged" },
  );
  assert.equal(tagged.text, "Topic-tagged body text remains the source body.");
  assert.deepEqual(tagged.topic_tags, ["恋愛"]);
  assert.deepEqual(
    tagged.observed_fields.find((item) => item.field === "topic_tags").value,
    ["恋愛"],
  );
  const tagOnly = await extractor.extractPostDetail(
    fixturePage("post_detail_topic_tag_only.html"),
    { ...missingContext, pageUrl: "https://www.threads.net/@sample.user/post/TagOnly" },
  );
  assert.equal(tagOnly.text, null, "topic metadata is never promoted to source text");
  assert.deepEqual(tagOnly.topic_tags, ["夫婦関係"]);
  const genuineShort = await extractor.extractPostDetail(
    fixturePage("post_detail_genuine_short.html"),
    { ...missingContext, pageUrl: "https://www.threads.net/@sample.user/post/GenuineShort" },
  );
  assert.equal(genuineShort.text, "恋愛", "a structurally identified body may be one word");
  assert.deepEqual(genuineShort.topic_tags, ["恋愛"]);

  const sequenced = await extractor.extractPostDetail(
    fixturePage("post_detail_sequence_indicator.html"),
    { ...missingContext, pageUrl: "https://www.threads.net/@sample.user/post/Sequenced" },
  );
  assert.equal(sequenced.text, "Sequence body remains author content.");
  assert.equal(sequenced.raw_sequence_indicator, "1 / 4");
  assert.equal(sequenced.thread_position, 1);
  assert.equal(sequenced.thread_total, 4);
  assert.deepEqual(extractor.threadExtractionDiagnostic(
    fixturePage("post_detail_sequence_indicator.html"),
    "https://www.threads.net/@sample.user/post/Sequenced",
  ).exclusion_reasons, {});
  assert.equal(sequenced.observed_fields.some(
    (item) => item.field === "raw_sequence_indicator" && item.value === "1 / 4"
  ), true);
  const authoredFraction = await extractor.extractPostDetail(
    fixturePage("post_detail_user_fraction.html"),
    { ...missingContext, pageUrl: "https://www.threads.net/@sample.user/post/AuthoredFraction" },
  );
  assert.equal(authoredFraction.text, "1 / 2",
    "matching author content is preserved without sequence-indicator DOM evidence");
  assert.equal(authoredFraction.raw_sequence_indicator, null);

  const headerExact = await extractor.extractPostDetail(
    fixturePage("post_detail_header_exact_view.html"),
    { ...missingContext, pageUrl: "https://www.threads.net/@sample.user/post/HeaderExact" },
  );
  assert.equal(headerExact.public_counters.view_count, null,
    "detail-page displays never populate exact view_count");
  assert.equal(headerExact.approximate_views, undefined,
    "a display without an explicit rounded unit is not relabelled as rounded evidence");
  assert.deepEqual(headerExact.display_views, {
    display: "表示6,400回", normalized_value: 6400, precision: "DISPLAY_EXACT",
    source: "POST_DETAIL_PAGE", view_band: "1K_10K",
    observed_at: context.collectedAt, extractor_version: extractor.version,
    normalizer_version: "display-views-normalizer-v1",
  });

  const activityExact = await extractor.extractPostDetail(
    fixturePage("post_detail_activity_exact_view.html"),
    { ...missingContext, pageUrl: "https://www.threads.net/@sample.user/post/ActivityExact" },
  );
  assert.equal(activityExact.public_counters.view_count, 64123);
  assert.equal(activityExact.metric_observation_statuses.view_count, "OBSERVED");
  assert.equal(activityExact.metric_observation_statuses.like_count, "NOT_PRESENT");
  assert.equal(
    activityExact.observed_fields.find((item) => item.field === "public_counters.view_count").value,
    64123,
  );

  const rolelessActivityExact = await extractor.extractPostDetail(
    fixturePage("post_detail_roleless_activity_exact_view.html"),
    { ...missingContext, pageUrl: "https://www.threads.net/@sample.user/post/RolelessActivityExact" },
  );
  assert.equal(rolelessActivityExact.public_counters.view_count, null,
    "role-less page text is not promoted to an exact Activity metric");

  const splitLabel = new Element({}, "閲覧数");
  const splitValue = new Element({}, "88,386");
  const splitParent = {
    parentElement: null,
    querySelectorAll(selector) { return selector === "span, div" ? [splitLabel, splitValue] : []; },
  };
  splitLabel.parentElement = splitParent;
  splitValue.parentElement = splitParent;
  const splitRoot = {
    querySelectorAll(selector) {
      if (selector === '[role="dialog"], [aria-modal="true"]') return [splitParent];
      return selector === "span, div" ? [splitLabel, splitValue] : [];
    },
  };
  splitParent.hidden = false;
  splitParent.getAttribute = () => null;
  assert.equal(extractor.activityViewCount(splitRoot), 88386,
    "a visible Activity label and adjacent exact integer are structurally paired");
  splitLabel.innerText = "いいね";
  splitLabel.textContent = "いいね";
  splitValue.innerText = "1,265";
  splitValue.textContent = "1,265";
  assert.equal(extractor.activityMetricValue(splitRoot, "like_count"), 1265,
    "engagement metrics use the same exact label/value pairing");

  assert.equal(extractor.exactNonnegativeInteger("Views 12K"), null);
  assert.equal(extractor.exactNonnegativeInteger("1.2K views"), null);
  assert.equal(extractor.pageViewCount(fixturePage("post_detail_missing_view.html")), null);
  assert.equal(
    extractor.approximatePageViews(
      fixturePage("post_detail_missing_view.html"), context.collectedAt,
    ).normalized_approx,
    64000,
  );
  assert.equal(
    extractor.exactDisplayPageViews(
      fixturePage("post_detail_display_4506.html"), context.collectedAt,
    ).normalized_value,
    4506,
  );
  assert.deepEqual(
    extractor.exactDisplayPageViews(
      fixturePage("post_detail_display_999.html"), context.collectedAt,
    ),
    {
      display: "表示999回", normalized_value: 999, precision: "DISPLAY_EXACT",
      source: "POST_DETAIL_PAGE", view_band: "LT_1K",
      observed_at: context.collectedAt, extractor_version: extractor.version,
      normalizer_version: "display-views-normalizer-v1",
    },
  );
  assert.equal(extractor.approximatePageViews(
    fixturePage("post_detail_display_12man.html"), context.collectedAt,
  ).normalized_approx, 12000);
  assert.equal(extractor.approximatePageViews(
    fixturePage("post_detail_display_10man.html"), context.collectedAt,
  ).normalized_approx, 100000);
  assert.equal(extractor.exactDisplayPageViews(
    fixturePage("post_detail_display_missing.html"), context.collectedAt,
  ), null);
  assert.equal(extractor.approximatePageViews(
    fixturePage("post_detail_display_missing.html"), context.collectedAt,
  ), null);
  assert.equal(extractor.exactDisplayPageViews(
    fixturePage("post_detail_display_malformed.html"), context.collectedAt,
  ), null);
  assert.equal(extractor.approximatePageViews(
    fixturePage("post_detail_display_malformed.html"), context.collectedAt,
  ), null);
  assert.equal(extractor.activityViewCount(fixturePage("post_detail_missing_view.html")), null);
  assert.equal(extractor.exactNonnegativeInteger("Views 0"), 0);
  assert.equal(extractor.canonicalPostUrl("javascript:alert(1)", context.pageUrl), null);
  assert.equal(extractor.recognizePostDetail(page, "https://www.threads.net/@other/post/Elsewhere"), false);
  assert.equal(await extractor.extractPostDetail(page, { ...context, pageUrl: "https://www.threads.net/search?q=x" }), null);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
