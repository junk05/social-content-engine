"use strict";

(function exposeDetailAction(scope) {
  const BUTTON_ATTRIBUTE = "data-sce-detail-action";
  const CONTRACT_VERSION = "M3_BROWSER_DETAIL_ATTEMPT_V1";
  const MAX_CONTAINER_ASCENT = 12;

  function sendMessage(message) {
    return new Promise((resolve) => {
      chrome.runtime.sendMessage(message, (response) => {
        if (chrome.runtime.lastError) resolve({ accepted: false, reason: "runtime_error" });
        else resolve(response || { accepted: false, reason: "empty_response" });
      });
    });
  }

  function failure(postUrl, attemptedAt, type, reason) {
    return {
      post_url: postUrl, attempted_at: attemptedAt,
      extractor_version: scope.SCE_THREADS_POST_DETAIL_EXTRACTOR.version,
      contract_version: CONTRACT_VERSION, failure_type: type, failure_reason: reason,
    };
  }

  function resolveDetailContainer(permalink) {
    let candidate = permalink.parentElement;
    let resolved = null;
    for (let depth = 0; candidate && depth < MAX_CONTAINER_ASCENT; depth += 1) {
      const postLinks = candidate.querySelectorAll('a[href*="/post/"]');
      const times = candidate.querySelectorAll("time[datetime]");
      if (postLinks.length > 2 || times.length > 1) break;
      if (postLinks.length >= 1 && times.length === 1) resolved = candidate;
      candidate = candidate.parentElement;
    }
    return resolved;
  }

  function install(root = document, pageUrl = location.href) {
    const extractor = scope.SCE_THREADS_POST_DETAIL_EXTRACTOR;
    if (!extractor.recognizePostDetail(root, pageUrl)) return null;
    if (root.querySelector("[" + BUTTON_ATTRIBUTE + "]")) return null;
    const canonicalPage = extractor.canonicalPostUrl(pageUrl, pageUrl);
    const permalink = Array.from(root.querySelectorAll('a[href*="/post/"]')).find(
      (link) => extractor.canonicalPostUrl(link.getAttribute("href"), pageUrl) === canonicalPage,
    );
    const anchor = permalink && resolveDetailContainer(permalink);
    if (!anchor) return null;
    const button = root.createElement("button");
    button.type = "button";
    button.setAttribute(BUTTON_ATTRIBUTE, "true");
    button.textContent = "詳細収集";
    button.addEventListener("click", async () => {
      const attemptedAt = new Date().toISOString();
      const postUrl = extractor.canonicalPostUrl(location.href, location.href);
      button.disabled = true;
      button.textContent = "収集中";
      try {
        const observation = await extractor.extractPostDetail(root, {
          pageUrl: location.href, collectedAt: attemptedAt,
        });
        if (!observation || !postUrl) {
          if (postUrl) await sendMessage({
            type: "SCE_DETAIL_FAILURE",
            failure: failure(postUrl, attemptedAt, "VALIDATION_FAILED", "INVALID_OBSERVATION"),
          });
          button.textContent = "詳細収集失敗";
          return;
        }
        const result = await sendMessage({ type: "SCE_OBSERVATION_READY", observation });
        if (result.accepted) {
          button.textContent = "✓ 詳細収集済み";
          return;
        }
        const timeout = result.reason === "timeout";
        const network = result.reason === "network_error" || result.reason === "runtime_error";
        await sendMessage({
          type: "SCE_DETAIL_FAILURE",
          failure: failure(
            postUrl, attemptedAt,
            timeout ? "TIMEOUT" : (network ? "NAVIGATION_FAILED" : "VALIDATION_FAILED"),
            timeout ? "TIME_LIMIT_EXCEEDED" : (network ? "NETWORK_ERROR" : "INVALID_OBSERVATION"),
          ),
        });
        button.textContent = "詳細収集失敗";
      } catch (_error) {
        if (postUrl) await sendMessage({
          type: "SCE_DETAIL_FAILURE",
          failure: failure(
            postUrl, attemptedAt, "EXTRACTION_FAILED", "EXPECTED_FIELD_MISSING"
          ),
        });
        button.textContent = "詳細収集失敗";
      } finally {
        if (button.textContent !== "✓ 詳細収集済み") button.disabled = false;
      }
    });
    anchor.append(button);
    return button;
  }

  scope.SCE_DETAIL_ACTION = Object.freeze({ install, resolveDetailContainer });
})(globalThis);
