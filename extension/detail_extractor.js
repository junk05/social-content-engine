"use strict";

// Versioned, read-only extraction for an already open Threads post-detail page.
// Navigation, batching, DOM observation, and transport are intentionally absent.
(function exposeThreadsPostDetailExtractor(scope) {
  const VERSION = "threads_post_detail_extractor_v16";
  const ROOT_RELATIONSHIP_EVIDENCE = "ROOT_DETAIL_PAGE";
  const SELF_REPLY_RELATIONSHIP_EVIDENCE = "DOM_CONTIGUOUS_ROOT_AUTHOR_CHAIN";
  const APPROXIMATE_VIEWS_NORMALIZER_VERSION = "rounded-views-normalizer-v1";
  const DISPLAY_VIEWS_NORMALIZER_VERSION = "display-views-normalizer-v1";
  const ENGAGEMENT_DISPLAY_NORMALIZER_VERSION = "engagement-display-normalizer-v1";
  const SURFACE = "threads_post_detail";
  const COUNTERS = Object.freeze({
    view_count: ["表示", "view"], like_count: ["いいね", "like"],
    reply_count: ["返信", "reply"], repost_count: ["再投稿", "repost"],
    quote_count: ["引用", "quote"], share_count: ["シェア", "share"],
  });
  const ACTIVITY_LABELS = Object.freeze({
    view_count: /^(?:閲覧数|ビュー|views?|表示)$/i,
    like_count: /^(?:いいね|likes?)$/i,
    reply_count: /^(?:返信|リプライ|repl(?:y|ies))$/i,
    repost_count: /^(?:再投稿|reposts?)$/i,
    quote_count: /^(?:引用|quotes?)$/i,
    share_count: /^(?:シェア|shares?)$/i,
  });
  const ENGAGEMENT_LABELS = Object.freeze({
    like_count: /(?:^|\s)(?:いいね|likes?)(?:\s|$)/i,
    reply_count: /(?:^|\s)(?:返信|リプライ|comments?|repl(?:y|ies))(?:\s|$)/i,
    repost_count: /(?:^|\s)(?:再投稿|reposts?)(?:\s|$)/i,
    quote_count: /(?:^|\s)(?:引用|quotes?)(?:\s|$)/i,
    share_count: /(?:^|\s)(?:シェア|shares?)(?:\s|$)/i,
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

  function isVisible(element) {
    return Boolean(element) && !element.hidden
      && (typeof element.getAttribute !== "function"
        || element.getAttribute("aria-hidden") !== "true");
  }
  function cleanText(value) {
    if (typeof value !== "string") return null;
    const cleaned = value.replace(/\s+/g, " ").trim();
    return cleaned || null;
  }
  function semanticPublicationTime(timeElement) {
    const raw = cleanText(timeElement && timeElement.getAttribute("datetime"));
    if (!raw) {
      return {
        published_at_raw: null, published_at: null,
        published_timezone_basis: "NOT_OBSERVED",
      };
    }
    // A semantic datetime must carry an explicit offset.  Do not translate a
    // relative label or a timezone-less wall time into a publication instant.
    const explicitOffset = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(raw);
    const parsed = explicitOffset ? Date.parse(raw) : Number.NaN;
    if (!Number.isFinite(parsed)) {
      return {
        published_at_raw: raw, published_at: null,
        published_timezone_basis: "NOT_OBSERVED",
      };
    }
    return {
      published_at_raw: raw,
      // Preserve the source's explicit offset as the local calculation basis;
      // normalize UTC Z to its equivalent explicit ISO-8601 offset.
      published_at: raw.endsWith("Z") || raw.endsWith("z")
        ? raw.slice(0, -1) + "+00:00" : raw,
      published_timezone_basis: "TIME_DATETIME_EXPLICIT_OFFSET",
    };
  }
  function renderedText(element) {
    const rendered = cleanText(typeof element.innerText === "string" ? element.innerText : null);
    if (rendered) return rendered;
    return cleanText(typeof element.textContent === "string" ? element.textContent : null);
  }
  const TOPIC_SELECTOR = [
    '[data-testid="topic-tag"]', '[data-topic-tag]',
    'a[href*="serp_type=tags"]', 'a[href*="serp_type=tag"]',
    'a[href*="/topic/"]', 'a[href*="/t/"]',
    '[role="link"][aria-label*="トピック"]',
  ].join(", ");
  function isTopicElement(element) {
    if (!element || typeof element.closest !== "function") return false;
    return Boolean(element.closest(TOPIC_SELECTOR));
  }
  function visibleTopicTags(root) {
    const values = [];
    const seen = new Set();
    for (const element of root.querySelectorAll(TOPIC_SELECTOR)) {
      if (!isVisible(element)) continue;
      const value = renderedText(element);
      if (!value || value.length > 100 || seen.has(value)) continue;
      seen.add(value);
      values.push(value);
    }
    return values;
  }
  const SEQUENCE_INDICATOR_SELECTOR = [
    'div.x1rg5ohu', '[data-testid="thread-sequence-indicator"]',
    '[data-thread-sequence-indicator]', '[aria-label*="スレッド"][aria-label*="/"]',
  ].join(", ");
  function visibleSequenceIndicator(root) {
    for (const element of root.querySelectorAll(SEQUENCE_INDICATOR_SELECTOR)) {
      if (!isVisible(element)) continue;
      const raw = renderedText(element);
      const match = raw ? raw.match(/^\s*(\d+)\s*\/\s*(\d+)\s*$/) : null;
      if (!match) continue;
      const position = Number(match[1]);
      const total = Number(match[2]);
      if (!Number.isSafeInteger(position) || !Number.isSafeInteger(total)
          || position < 1 || total < 1 || position > total) continue;
      return { raw_sequence_indicator: raw, thread_position: position, thread_total: total };
    }
    return null;
  }
  function withoutObservedSequenceIndicator(value, sequenceIndicator) {
    if (!value || !sequenceIndicator) return value;
    const raw = sequenceIndicator.raw_sequence_indicator;
    if (value === raw) return null;
    if (!value.endsWith(raw)) return value;
    return cleanText(value.slice(0, -raw.length));
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
  function metricHint(value) {
    const text = cleanText(value);
    if (!text) return null;
    for (const [name, pattern] of Object.entries(ENGAGEMENT_LABELS)) {
      if (pattern.test(text)) return name;
    }
    return null;
  }
  function numericDisplayShape(value) {
    const text = cleanText(value);
    if (!text) return null;
    const ascii = asciiNumericDisplay(text);
    if (/^(?:0|[1-9][0-9]{0,2}(?:,[0-9]{3})*|[1-9][0-9]*)$/.test(ascii)) return "DISPLAY_EXACT";
    if (/^[0-9]+(?:\.[0-9]+)?\s*(?:千|万|億|[KMB])$/i.test(ascii)) return "ROUNDED";
    return null;
  }
  function normalizedEngagementDisplay(display, metricName, observedAt, relationshipEvidence) {
    const shape = numericDisplayShape(display);
    if (!shape) return null;
    const ascii = asciiNumericDisplay(display).replace(/\s+/g, "");
    let normalizedValue = exactNonnegativeInteger(ascii);
    if (normalizedValue === null && shape === "ROUNDED") {
      const match = ascii.match(/^([0-9]+(?:\.[0-9]+)?)(千|万|億|K|M|B)$/i);
      const multipliers = { 千: 1000, 万: 10000, 億: 100000000, K: 1000, M: 1000000, B: 1000000000 };
      if (!match || !Object.hasOwn(multipliers, match[2].toUpperCase())) return null;
      normalizedValue = Math.round(Number(match[1]) * multipliers[match[2].toUpperCase()]);
    }
    if (!Number.isSafeInteger(normalizedValue) || normalizedValue < 0) return null;
    return {
      raw_display: display, normalized_value: normalizedValue, precision: shape,
      source: "POST_DETAIL_ENGAGEMENT_CONTROL", observed_at: observedAt,
      extractor_version: VERSION, normalizer_version: ENGAGEMENT_DISPLAY_NORMALIZER_VERSION,
      relationship_evidence: relationshipEvidence, metric_name: metricName,
    };
  }
  function localNumericDisplay(container) {
    if (!container || typeof container.querySelectorAll !== "function") return null;
    const values = new Set();
    for (const element of [container, ...container.querySelectorAll("span, div")]) {
      if (!isVisible(element)) continue;
      const display = renderedText(element);
      if (numericDisplayShape(display)) values.add(display);
    }
    return values.size === 1 ? Array.from(values)[0] : null;
  }
  function metricIconHint(container) {
    if (!container || typeof container.querySelectorAll !== "function") return null;
    for (const icon of container.querySelectorAll('svg[role="img"][aria-label]')) {
      if (!isVisible(icon)) continue;
      const hint = metricHint(icon.getAttribute("aria-label"));
      if (hint) return hint;
    }
    return null;
  }
  function visibleEngagementMetricDisplays(root, observedAt) {
    const displays = {};
    const controls = Array.from(root.querySelectorAll('[role="button"]')).filter(isVisible);
    const indexedControls = controls.map((control) => ({
      control, metric_name: metricIconHint(control), display: localNumericDisplay(control),
    }));
    for (const item of indexedControls) {
      if (!item.metric_name || !item.display || item.metric_name === "share_count") continue;
      const metric = normalizedEngagementDisplay(
        item.display, item.metric_name, observedAt,
        "SVG_ARIA_LABEL_AND_LOCAL_NUMERIC_DISPLAY",
      );
      if (metric) displays[item.metric_name] = metric;
    }
    // In the observed Threads control row, Like is the unlabelled numeric
    // action immediately preceding a semantically-labelled Reply action.
    // This is constrained to the engagement action order, never post text.
    const replyIndex = indexedControls.findIndex(
      (item) => item.metric_name === "reply_count" && item.display,
    );
    if (replyIndex > 0 && !displays.like_count) {
      const likeCandidate = indexedControls[replyIndex - 1];
      if (likeCandidate && likeCandidate.metric_name === null && likeCandidate.display) {
        const metric = normalizedEngagementDisplay(
          likeCandidate.display, "like_count", observedAt,
          "ACTION_ORDER_PRECEDING_REPLY_AND_LOCAL_NUMERIC_DISPLAY",
        );
        if (metric) displays.like_count = metric;
      }
    }
    return displays;
  }
  function diagnosticNode(element) {
    if (!element) return null;
    const tag = typeof element.tagName === "string" ? element.tagName : null;
    const role = typeof element.getAttribute === "function" ? element.getAttribute("role") : null;
    const aria = typeof element.getAttribute === "function" ? cleanText(element.getAttribute("aria-label")) : null;
    const text = renderedText(element);
    const rawDisplay = numericDisplayShape(text) ? text : null;
    const labelHint = metricHint(aria) || metricHint(text);
    return {
      tag, role, metric_hint: labelHint,
      raw_display: rawDisplay,
      display_shape: rawDisplay ? numericDisplayShape(rawDisplay) : null,
      aria_label: (labelHint || rawDisplay) ? aria : null,
      has_svg_descendant: typeof element.querySelector === "function" && Boolean(element.querySelector("svg")),
    };
  }
  function directDiagnosticChildren(element) {
    if (!element || typeof element.querySelectorAll !== "function") return [];
    const values = [];
    const seen = new Set();
    for (const child of element.querySelectorAll("span, div, button, [role=button], [aria-label]")) {
      if (!isVisible(child)) continue;
      const node = diagnosticNode(child);
      if (!node || (!node.metric_hint && !node.raw_display)) continue;
      const key = JSON.stringify(node);
      if (seen.has(key)) continue;
      seen.add(key);
      values.push(node);
      if (values.length >= 12) break;
    }
    return values;
  }
  function auditEngagementControls(root, pageUrl) {
    const readiness = postDetailReadiness(root, pageUrl);
    if (!readiness.postRootFound) {
      return { diagnostic_version: "engagement_control_diagnostic_v1",
        canonical_detail: readiness.canonicalPage && readiness.permalinkFound,
        control_candidates: [], numeric_candidates: [] };
    }
    const postRoot = rootPostContainer(root, pageUrl);
    const controls = [];
    const numericCandidates = [];
    const controlSeen = new Set();
    const numericSeen = new Set();
    for (const element of postRoot.querySelectorAll("button, [role=button], [aria-label]")) {
      if (!isVisible(element)) continue;
      const node = diagnosticNode(element);
      if (!node || (!node.metric_hint && !node.raw_display && !node.has_svg_descendant)) continue;
      const parent = diagnosticNode(element.parentElement);
      const record = { control_index: controls.length, ...node,
        parent: parent ? { tag: parent.tag, role: parent.role, has_svg_descendant: parent.has_svg_descendant } : null,
        nearby_metric_or_numeric_nodes: directDiagnosticChildren(element.parentElement) };
      const key = JSON.stringify(record);
      if (controlSeen.has(key)) continue;
      controlSeen.add(key);
      controls.push(record);
    }
    for (const element of postRoot.querySelectorAll("span, div")) {
      if (!isVisible(element)) continue;
      const node = diagnosticNode(element);
      if (!node || !node.raw_display) continue;
      let surface = element.parentElement;
      let engagementContext = false;
      for (let depth = 0; surface && depth < 3; depth += 1) {
        const context = diagnosticNode(surface);
        if (context && (context.has_svg_descendant || context.metric_hint)) {
          engagementContext = true;
          break;
        }
        surface = surface.parentElement;
      }
      if (!engagementContext) continue;
      const parent = diagnosticNode(element.parentElement);
      const record = { candidate_index: numericCandidates.length,
        raw_display: node.raw_display, display_shape: node.display_shape,
        metric_hint: node.metric_hint || (parent && parent.metric_hint) || null,
        parent: parent ? { tag: parent.tag, role: parent.role, has_svg_descendant: parent.has_svg_descendant } : null,
        nearby_metric_or_numeric_nodes: directDiagnosticChildren(element.parentElement) };
      const key = JSON.stringify(record);
      if (numericSeen.has(key)) continue;
      numericSeen.add(key);
      numericCandidates.push(record);
    }
    return { diagnostic_version: "engagement_control_diagnostic_v1",
      canonical_detail: readiness.canonicalPage && readiness.permalinkFound,
      control_candidates: controls, numeric_candidates: numericCandidates };
  }
  function findPermalink(root, pageUrl, expectedCanonical = null) {
    let fallback = null;
    for (const link of root.querySelectorAll('a[href*="/post/"]')) {
      if (!isVisible(link)) continue;
      const canonical = canonicalPostUrl(link.getAttribute("href"), pageUrl);
      if (canonical && (!expectedCanonical || canonical === expectedCanonical)) {
        const candidate = { link, canonical };
        if (typeof link.querySelector === "function" && link.querySelector("time[datetime]")) {
          return candidate;
        }
        if (fallback === null) fallback = candidate;
      }
    }
    return fallback;
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
  function extractVisibleThreadNodes(root, pageUrl) {
    const rootUrl = canonicalPostUrl(pageUrl, pageUrl);
    if (!rootUrl) return [];
    const rootUsername = rootUrl.match(/\/@([^/]+)\/post\//)[1].toLowerCase();
    const seen = new Set([rootUrl]);
    const nodes = [{
      post_url: rootUrl, root_post_url: rootUrl, reply_to_post_url: null,
      same_author_as_root: true, relationship_evidence: ROOT_RELATIONSHIP_EVIDENCE,
    }];
    const indicator = visibleSequenceIndicator(rootPostContainer(root, pageUrl) || root);
    const maxNodes = indicator && indicator.thread_position === 1 && indicator.thread_total > 1
      ? indicator.thread_total : null;
    let rootObserved = false;
    for (const link of root.querySelectorAll('a[href*="/post/"]')) {
      if (!isVisible(link)) continue;
      const postUrl = canonicalPostUrl(link.getAttribute("href"), pageUrl);
      if (!postUrl) continue;
      if (postUrl === rootUrl) {
        rootObserved = true;
        continue;
      }
      if (!rootObserved || seen.has(postUrl)) continue;
      // Only timestamp permalinks identify nodes in the rendered conversation
      // order. Quoted/related post links inside a card are not branch nodes.
      if (typeof link.querySelector === "function" && !link.querySelector("time[datetime]")) {
        continue;
      }
      // A root `1 / N` bounds this observed author-owned sequence. A later
      // same-author post may begin another sequence; never merge it merely
      // because the flat DOM order remains contiguous.
      if (maxNodes !== null && nodes.length >= maxNodes) break;
      const nodeUsername = postUrl.match(/\/@([^/]+)\/post\//)[1].toLowerCase();
      // The author-owned continuation is the contiguous root-author prefix.
      // Once the conversation enters another author, that branch is closed and
      // a later root-author reply must never rejoin the Pattern sequence.
      if (nodeUsername !== rootUsername) break;
      seen.add(postUrl);
      nodes.push({ post_url: postUrl,
        root_post_url: rootUrl, reply_to_post_url: null,
        same_author_as_root: true,
        relationship_evidence: SELF_REPLY_RELATIONSHIP_EVIDENCE });
    }
    return nodes.map((node, sequencePosition) => ({
      ...node, sequence_position: sequencePosition,
    }));
  }
  function diagnoseVisibleThread(root, pageUrl) {
    const rootUrl = canonicalPostUrl(pageUrl, pageUrl);
    if (!rootUrl || !root || typeof root.querySelectorAll !== "function") {
      return {
        diagnostic_version: "thread_candidate_diagnostic_v1",
        visible_post_nodes: 0, root_nodes: 0, discovered_candidates: 0,
        direct_root_author_candidates: 0, other_author_candidates: 0,
        root_author_after_other_boundary: 0,
        root_author_replies_under_other_author: "NOT_OBSERVED",
        final_eligible_nodes: 0, excluded_candidates: 0,
        exclusion_reasons: { INVALID_DETAIL_PAGE: 1 },
        relationship_evidence: [], candidates: [],
      };
    }
    const rootUsername = rootUrl.match(/\/@([^/]+)\/post\//)[1].toLowerCase();
    const seen = new Set();
    const candidates = [];
    let rootObserved = false;
    let rootNodes = 0;
    let otherAuthorBoundary = false;
    let eligiblePosition = 0;
    const indicator = visibleSequenceIndicator(rootPostContainer(root, pageUrl) || root);
    const maxNodes = indicator && indicator.thread_position === 1 && indicator.thread_total > 1
      ? indicator.thread_total : null;
    for (const link of root.querySelectorAll('a[href*="/post/"]')) {
      if (!isVisible(link)) continue;
      const postUrl = canonicalPostUrl(link.getAttribute("href"), pageUrl);
      if (!postUrl || seen.has(postUrl)) continue;
      const hasTimestamp = typeof link.querySelector === "function"
        && Boolean(link.querySelector("time[datetime]"));
      if (!hasTimestamp) continue;
      seen.add(postUrl);
      const isRoot = postUrl === rootUrl;
      const nodeUsername = postUrl.match(/\/@([^/]+)\/post\//)[1].toLowerCase();
      const sameAuthor = nodeUsername === rootUsername;
      let eligible = false;
      let reason;
      let evidence = null;
      if (isRoot) {
        rootObserved = true;
        rootNodes += 1;
        eligible = true;
        reason = "ROOT";
        evidence = ROOT_RELATIONSHIP_EVIDENCE;
      } else if (!rootObserved) {
        reason = "BEFORE_ROOT";
      } else if (!sameAuthor) {
        otherAuthorBoundary = true;
        reason = "OTHER_AUTHOR_BOUNDARY";
      } else if (otherAuthorBoundary) {
        reason = "ROOT_AUTHOR_AFTER_OTHER_AUTHOR_BOUNDARY";
      } else if (maxNodes !== null && eligiblePosition >= maxNodes - 1) {
        reason = "AFTER_EXPECTED_THREAD_TOTAL";
      } else {
        eligiblePosition += 1;
        eligible = true;
        reason = "CONTIGUOUS_ROOT_AUTHOR_CHAIN";
        evidence = SELF_REPLY_RELATIONSHIP_EVIDENCE;
      }
      candidates.push({
        ordinal: candidates.length, node_type: isRoot ? "ROOT" : "POST",
        same_author_as_root: sameAuthor, has_timestamp_permalink: hasTimestamp,
        eligible, eligible_sequence_position: eligible ? eligiblePosition : null,
        reason, relationship_evidence: evidence,
      });
    }
    const exclusions = {};
    for (const candidate of candidates) {
      if (candidate.eligible) continue;
      exclusions[candidate.reason] = (exclusions[candidate.reason] || 0) + 1;
    }
    const afterBoundary = candidates.filter(
      (item) => item.reason === "ROOT_AUTHOR_AFTER_OTHER_AUTHOR_BOUNDARY",
    ).length;
    return {
      diagnostic_version: "thread_candidate_diagnostic_v1",
      visible_post_nodes: candidates.length,
      root_nodes: rootNodes,
      discovered_candidates: candidates.length,
      direct_root_author_candidates: candidates.filter(
        (item) => item.reason === "CONTIGUOUS_ROOT_AUTHOR_CHAIN",
      ).length,
      other_author_candidates: candidates.filter(
        (item) => item.reason === "OTHER_AUTHOR_BOUNDARY",
      ).length,
      root_author_after_other_boundary: afterBoundary,
      // A flat permalink scan cannot prove that a later root-author node is a
      // reply under the intervening author. Preserve that relationship as
      // unknown rather than relabelling it from username/order alone.
      root_author_replies_under_other_author: "NOT_OBSERVED",
      final_eligible_nodes: candidates.filter((item) => item.eligible).length,
      excluded_candidates: candidates.filter((item) => !item.eligible).length,
      exclusion_reasons: exclusions,
      relationship_evidence: Array.from(new Set(candidates
        .map((item) => item.relationship_evidence).filter(Boolean))),
      candidates,
    };
  }
  function threadExtractionDiagnostic(root, pageUrl) {
    const diagnostic = diagnoseVisibleThread(root, pageUrl);
    return {
      diagnostic_version: diagnostic.diagnostic_version,
      visible_post_nodes: diagnostic.visible_post_nodes,
      discovered_candidates: diagnostic.discovered_candidates,
      direct_root_author_candidates: diagnostic.direct_root_author_candidates,
      other_author_candidates: diagnostic.other_author_candidates,
      root_author_after_other_boundary: diagnostic.root_author_after_other_boundary,
      final_eligible_nodes: diagnostic.final_eligible_nodes,
      excluded_candidates: diagnostic.excluded_candidates,
      exclusion_reasons: diagnostic.exclusion_reasons,
    };
  }
  function rootPostContainer(root, pageUrl) {
    const canonical = canonicalPostUrl(pageUrl, pageUrl);
    const permalink = findPermalink(root, pageUrl, canonical);
    if (!permalink) return null;
    // DOM-less sanitized fixture adapters do not expose ancestry. Real browser
    // elements always expose parentElement and take the bounded path below.
    if (!("parentElement" in permalink.link)) return root;
    let candidate = permalink.link.parentElement;
    let resolved = null;
    for (let depth = 0; candidate && depth < 12; depth += 1) {
      const links = Array.from(candidate.querySelectorAll('a[href*="/post/"]'))
        .map((link) => canonicalPostUrl(link.getAttribute("href"), pageUrl)).filter(Boolean);
      const times = candidate.querySelectorAll("time[datetime]");
      if (times.length > 1 || new Set(links).size > 1) break;
      if (times.length === 1 && links.includes(canonical)) resolved = candidate;
      candidate = candidate.parentElement;
    }
    return resolved;
  }
  function postDetailReadiness(root, pageUrl) {
    const canonical = canonicalPostUrl(pageUrl, pageUrl);
    const post = canonical ? findPermalink(root, pageUrl, canonical) : null;
    const postRoot = post ? rootPostContainer(root, pageUrl) : null;
    const time = postRoot ? postRoot.querySelector("time[datetime]") : null;
    return {
      canonicalPage: canonical !== null,
      permalinkFound: post !== null,
      postRootFound: postRoot !== null,
      timestampFound: Boolean(time && cleanText(time.getAttribute("datetime"))),
    };
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
  function visibleCounters(root, engagementDisplays = {}) {
    const counters = {};
    for (const name of Object.keys(COUNTERS)) {
      counters[name] = engagementDisplays[name]?.normalized_value ?? null;
    }
    for (const element of root.querySelectorAll("[aria-label]")) {
      if (!isVisible(element)) continue;
      const label = element.getAttribute("aria-label") || "";
      const lower = label.toLowerCase();
      for (const [name, markers] of Object.entries(COUNTERS)) {
        if (!markers.some((marker) => lower.includes(marker))) continue;
        const value = exactNonnegativeInteger(label);
        if (value !== null && counters[name] === null) counters[name] = value;
      }
    }
    return counters;
  }
  function pageViewCount(root) {
    for (const element of root.querySelectorAll("span, div")) {
      if (!isVisible(element)) continue;
      const label = renderedText(element);
      if (!label) continue;
      const match = label.match(/^表示\s*([0-9][0-9,]*)\s*回$/);
      if (!match) continue;
      const value = exactNonnegativeInteger(match[1]);
      if (value !== null) return value;
    }
    return null;
  }
  function viewBand(value) {
    if (value < 1000) return "LT_1K";
    if (value < 10000) return "1K_10K";
    if (value < 100000) return "10K_100K";
    if (value < 1000000) return "100K_1M";
    return "1M_PLUS";
  }
  function asciiNumericDisplay(value) {
    return value.replace(/[０-９]/g, (digit) => String(digit.charCodeAt(0) - 0xFF10))
      .replaceAll("，", ",");
  }
  function exactDisplayPageViews(root, observedAt) {
    const patterns = [
      /^(?:表示\s*)?([0-9０-９][0-9０-９,，]*)\s*(?:回|views?)$/i,
      /^表示\s*([0-9０-９][0-9０-９,，]*)$/i,
    ];
    for (const element of root.querySelectorAll("span, div")) {
      if (!isVisible(element)) continue;
      const display = renderedText(element);
      if (!display || display.length > 32) continue;
      let token = null;
      for (const pattern of patterns) {
        const match = display.match(pattern);
        if (match) { token = asciiNumericDisplay(match[1]); break; }
      }
      if (token === null) continue;
      const normalizedValue = exactNonnegativeInteger(token);
      if (normalizedValue === null) continue;
      return {
        display, normalized_value: normalizedValue, precision: "DISPLAY_EXACT",
        source: "POST_DETAIL_PAGE", view_band: viewBand(normalizedValue),
        observed_at: observedAt, extractor_version: VERSION,
        normalizer_version: DISPLAY_VIEWS_NORMALIZER_VERSION,
      };
    }
    return null;
  }
  function approximatePageViews(root, observedAt) {
    const patterns = [
      /^(表示)\s*([0-9]+(?:\.[0-9]+)?)\s*(千|万|億)\s*回$/i,
      /^([0-9]+(?:\.[0-9]+)?)\s*([KMB])\s*(views?)$/i,
    ];
    const multipliers = { 千: 1000, 万: 10000, 億: 100000000, K: 1000, M: 1000000, B: 1000000000 };
    for (const element of root.querySelectorAll("span, div")) {
      if (!isVisible(element)) continue;
      const display = renderedText(element);
      if (!display || display.length > 32) continue;
      const comparable = asciiNumericDisplay(display);
      let numericToken = null;
      let unit = null;
      for (const pattern of patterns) {
        const match = comparable.match(pattern);
        if (!match) continue;
        if (match.length === 4 && match[1] === "表示") {
          numericToken = match[2]; unit = match[3];
        } else {
          numericToken = match[1]; unit = match[2].toUpperCase();
        }
        break;
      }
      if (numericToken === null || !Object.hasOwn(multipliers, unit)) continue;
      const normalizedApprox = Math.round(Number(numericToken) * multipliers[unit]);
      if (!Number.isSafeInteger(normalizedApprox) || normalizedApprox < 0) continue;
      return {
        display, normalized_approx: normalizedApprox, precision: "ROUNDED",
        source: "POST_DETAIL_PAGE", view_band: viewBand(normalizedApprox),
        observed_at: observedAt, extractor_version: VERSION,
        normalizer_version: APPROXIMATE_VIEWS_NORMALIZER_VERSION,
      };
    }
    return null;
  }
  function activityMetricValue(root, counterName) {
    // Threads exposes a rounded page-header count (for example, "表示6.4万回")
    // and may expose the exact count only after the person opens Activity.  We
    // read the already-visible dialog; opening it remains a human action.
    const labelPattern = ACTIVITY_LABELS[counterName];
    if (!labelPattern) return null;
    const containers = Array.from(root.querySelectorAll('[role="dialog"], [aria-modal="true"]'))
      .filter(isVisible);
    for (const container of containers) {
      const elements = [container,
        ...container.querySelectorAll("span, div"),
        ...container.querySelectorAll("p"),
      ];
      for (const element of elements) {
        if (!isVisible(element)) continue;
        const label = renderedText(element);
        if (!label) continue;
        // The Japanese activity sheet has used both "閲覧数 64,123" and
        // "表示 64,123 回".  The page header can be rounded ("表示6.4万回"),
        // so retain the exact-integer requirement rather than interpreting a
        // rounded header as an exact Activity value.
        const match = label.match(/^(.+?)\s*[:：]?\s*([0-9][0-9,]*)\s*(?:件|回|views?)?$/i);
        if (!match || !labelPattern.test(match[1])) continue;
        const value = exactNonnegativeInteger(match[2]);
        if (value !== null) return value;
      }
      const labels = elements.filter((element) => {
        if (!isVisible(element)) return false;
        const label = renderedText(element);
        return label !== null && labelPattern.test(label);
      });
      for (const label of labels) {
        let neighborhood = label.parentElement;
        for (let depth = 0; neighborhood && depth < 4; depth += 1) {
          const candidates = [
            ...neighborhood.querySelectorAll("span, div"),
            ...neighborhood.querySelectorAll("p"),
          ];
          for (const candidate of candidates) {
            if (!isVisible(candidate)) continue;
            const text = renderedText(candidate);
            if (!text || !/^(?:0|[1-9][0-9]{0,2}(?:,[0-9]{3})*|[1-9][0-9]*)$/.test(text)) {
              continue;
            }
            const value = exactNonnegativeInteger(text);
            if (value !== null) return value;
          }
          neighborhood = neighborhood.parentElement;
        }
      }
    }
    return null;
  }
  function activityViewCount(root) { return activityMetricValue(root, "view_count"); }
  function visibleActivitySurface(root) {
    if (Array.from(root.querySelectorAll('[role="dialog"], [aria-modal="true"]'))
      .some(isVisible)) return true;
    return activityViewCount(root) !== null;
  }
  function activityMetricPresent(root, counterName) {
    const pattern = ACTIVITY_LABELS[counterName];
    if (!pattern) return false;
    for (const dialog of root.querySelectorAll('[role="dialog"], [aria-modal="true"]')) {
      if (!isVisible(dialog)) continue;
      for (const element of dialog.querySelectorAll("span, div, p")) {
        if (!isVisible(element)) continue;
        const text = renderedText(element);
        if (text && (pattern.test(text) || text.split(/\s+/).some((part) => pattern.test(part)))) {
          return true;
        }
      }
    }
    return false;
  }
  function visibleActivityDialogViewCount(root) {
    for (const dialog of root.querySelectorAll('[role="dialog"], [aria-modal="true"]')) {
      if (!isVisible(dialog)) continue;
      const value = activityViewCount(dialog);
      if (value !== null) return value;
    }
    return null;
  }
  function visibleActivityViewCount(root) {
    return visibleActivityDialogViewCount(root);
  }
  function visiblePostText(root, excludedValues, sequenceIndicator = null) {
    const excluded = new Set(excludedValues.filter(Boolean).map((value) => value.toLowerCase()));
    const dateMetadata = /^\d{4}[/-]\d{1,2}[/-]\d{1,2}$/;
    const relativeTimeMetadata = /^(?:\d+\s*(?:分|時間|日|週|ヶ月|か月|月|年|m|min|h|d|w|mo|y)|昨日|一昨日)$/i;
    for (const selector of ['[data-testid="post-text"]', '[dir="auto"]']) {
      const eligible = [];
      for (const candidate of root.querySelectorAll(selector)) {
        if (!isVisible(candidate)) continue;
        if (candidate.closest('a[href^="/@"], a[href*="/post/"], time, button, [role="button"]')) continue;
        if (isTopicElement(candidate)) continue;
        const value = withoutObservedSequenceIndicator(
          renderedText(candidate), sequenceIndicator,
        );
        if (value && !excluded.has(value.toLowerCase())
            && !dateMetadata.test(value) && !relativeTimeMetadata.test(value)) {
          eligible.push({ value, order: eligible.length });
        }
      }
      if (eligible.length) {
        // Explicit content containers win. On the fallback surface, choose the
        // richest remaining content node after structural metadata exclusion;
        // never reject a genuine short body merely because its wording also
        // resembles a topic label.
        eligible.sort((left, right) => right.value.length - left.value.length
          || left.order - right.order);
        return eligible[0].value;
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
    const postRoot = rootPostContainer(root, pageUrl);
    if (!postRoot) return null;
    const time = postRoot.querySelector("time[datetime]");
    const publication = semanticPublicationTime(time);
    if (!post) return null;
    // Keep timestamp as a compatibility alias. New callers must use the
    // explicit published_at semantics below.
    const timestamp = publication.published_at;
    const profile = profileValues(postRoot, post.canonical);
    // Header and engagement values describe the canonical page root. Thread
    // child extraction reuses the same document and must not inherit them.
    const includePageMetrics = context.includePageMetrics !== false;
    const engagementMetricDisplays = includePageMetrics
      ? visibleEngagementMetricDisplays(postRoot, collectedAt) : {};
    const counters = visibleCounters(postRoot, engagementMetricDisplays);
    for (const name of Object.keys(counters)) {
      if (counters[name] === null) counters[name] = activityMetricValue(root, name);
    }
    const approximateViews = includePageMetrics
      ? approximatePageViews(root, collectedAt) : null;
    const displayViews = includePageMetrics
      ? exactDisplayPageViews(root, collectedAt) : null;
    const views = displayViews !== null ? {
      raw_display: displayViews.display,
      normalized_value: displayViews.normalized_value,
      precision: displayViews.precision,
      display_format: "INTEGER",
      source: displayViews.source,
      view_band: displayViews.view_band,
      observed_at: displayViews.observed_at,
      extractor_version: displayViews.extractor_version,
      normalizer_version: displayViews.normalizer_version,
    } : approximateViews !== null ? {
      raw_display: approximateViews.display,
      normalized_value: approximateViews.normalized_approx,
      precision: approximateViews.precision,
      display_format: approximateViews.display.includes("億") ? "JAPANESE_OKU"
        : approximateViews.display.includes("万") ? "JAPANESE_MAN" : "OTHER_MAGNITUDE",
      source: approximateViews.source,
      view_band: approximateViews.view_band,
      observed_at: approximateViews.observed_at,
      extractor_version: approximateViews.extractor_version,
      normalizer_version: approximateViews.normalizer_version,
    } : null;
    const activityVisible = visibleActivitySurface(root);
    const metricStatuses = {};
    for (const [name, value] of Object.entries(counters)) {
      metricStatuses[name] = value !== null ? "OBSERVED"
        : activityVisible
          ? (activityMetricPresent(root, name) ? "EXTRACTION_FAILED" : "NOT_PRESENT")
          : "NOT_OBSERVED";
    }
    const counterLabels = Array.from(postRoot.querySelectorAll("[aria-label]"), (element) => isVisible(element) ? cleanText(element.getAttribute("aria-label")) : null);
    const sequenceIndicator = visibleSequenceIndicator(postRoot);
    const text = visiblePostText(
      postRoot, [profile.authorName, profile.username, publication.published_at_raw,
        publication.published_at, ...counterLabels],
      sequenceIndicator,
    );
    const topicTags = visibleTopicTags(postRoot);
    const media = mediaValues(postRoot);
    const observed = [];
    for (const [field, value] of [
      ["author_name", profile.authorName], ["username", profile.username], ["text", text],
      ["timestamp", timestamp], ["published_at_raw", publication.published_at_raw],
      ["published_at", publication.published_at],
      ["published_timezone_basis", publication.published_timezone_basis],
      ["media_type", media.mediaType], ["has_image", media.hasImage], ["has_video", media.hasVideo],
    ]) if (value !== null) observed.push(observationField(field, value, collectedAt));
    if (topicTags.length) observed.push(observationField("topic_tags", topicTags, collectedAt));
    if (sequenceIndicator) {
      for (const field of ["raw_sequence_indicator", "thread_position", "thread_total"]) {
        observed.push(observationField(field, sequenceIndicator[field], collectedAt));
      }
    }
    for (const [name, value] of Object.entries(counters)) if (value !== null) observed.push(observationField("public_counters." + name, value, collectedAt));
    const observation = {
      schema_version: 1, observation_type: "POST_DETAIL", source: "threads",
      post_url: post.canonical, source_post_id: null,
      author_name: profile.authorName, username: profile.username, text, topic_tags: topicTags,
      raw_sequence_indicator: sequenceIndicator?.raw_sequence_indicator ?? null,
      thread_position: sequenceIndicator?.thread_position ?? null,
      thread_total: sequenceIndicator?.thread_total ?? null, timestamp,
      published_at_raw: publication.published_at_raw,
      published_at: publication.published_at,
      published_timezone_basis: publication.published_timezone_basis,
      public_counters: counters, metric_observation_statuses: metricStatuses,
      media_type: media.mediaType, has_image: media.hasImage, has_video: media.hasVideo,
      collection_context: { surface: SURFACE, page_url: post.canonical, query: null, position: null },
      observed_fields: observed, collected_at: collectedAt, extractor_version: VERSION,
    };
    if (approximateViews !== null) observation.approximate_views = approximateViews;
    if (displayViews !== null) observation.display_views = displayViews;
    if (views !== null) observation.views = views;
    if (Object.keys(engagementMetricDisplays).length) {
      observation.engagement_metric_displays = engagementMetricDisplays;
    }
    observation.payload_sha256 = await sha256(observation);
    return observation;
  }
  async function extractVisibleThreadDetails(root, pageUrl, collectedAt) {
    const rootUrl = canonicalPostUrl(pageUrl, pageUrl);
    const details = [];
    for (const node of extractVisibleThreadNodes(root, pageUrl)) {
      if (node.post_url === rootUrl || node.same_author_as_root !== true) continue;
      const observation = await extractPostDetail(root, {
        pageUrl: node.post_url, collectedAt, includePageMetrics: false,
      });
      if (observation) details.push(observation);
    }
    return details;
  }
  scope.SCE_THREADS_POST_DETAIL_EXTRACTOR = Object.freeze({
    version: VERSION, canonicalPostUrl, exactNonnegativeInteger, pageViewCount, activityViewCount,
    auditEngagementControls, visibleEngagementMetricDisplays,
    semanticPublicationTime,
    approximatePageViews, exactDisplayPageViews, viewBand,
    activityMetricValue, activityMetricPresent, visibleActivitySurface, visibleActivityViewCount,
    recognizePostDetail, rootPostContainer, postDetailReadiness,
    visibleTopicTags, visibleSequenceIndicator, extractVisibleThreadNodes,
    diagnoseVisibleThread, threadExtractionDiagnostic, extractPostDetail,
    extractVisibleThreadDetails,
  });
})(globalThis);
