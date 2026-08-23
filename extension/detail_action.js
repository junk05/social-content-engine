"use strict";

(function exposeDetailAction(scope) {
  const BUTTON_ATTRIBUTE = "data-sce-detail-action";
  const ACTIVITY_BUTTON_ATTRIBUTE = "data-sce-detail-activity-action";
  const ENGAGEMENT_DIAGNOSTIC_ATTRIBUTE = "data-sce-engagement-diagnostic-action";
  const CONTRACT_VERSION = "M3_BROWSER_DETAIL_ATTEMPT_V1";
  const MAX_CONTAINER_ASCENT = 12;

  function renderThreadDiagnostic(root, anchor, diagnostic) {
    if (!diagnostic || !anchor || typeof root.createElement !== "function") return;
    let output = typeof root.querySelector === "function"
      ? root.querySelector("[data-sce-thread-diagnostic]") : null;
    if (!output) {
      output = root.createElement("pre");
      output.setAttribute("data-sce-thread-diagnostic", "true");
      output.style.cssText = "white-space:pre-wrap;font:12px/1.4 monospace;margin:8px;padding:8px;border:1px solid currentColor";
      anchor.append(output);
    }
    output.textContent = "Thread診断: " + JSON.stringify(diagnostic);
  }

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

  function createActionButton(root, pageUrl, attribute, label) {
    const extractor = scope.SCE_THREADS_POST_DETAIL_EXTRACTOR;
    const button = root.createElement("button");
    button.type = "button";
    button.setAttribute(attribute, "true");
    button.textContent = label;
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
          const diagnostic = typeof extractor.diagnoseVisibleThread === "function"
            ? extractor.diagnoseVisibleThread(root, location.href) : null;
          const nodes = extractor.extractVisibleThreadNodes(root, location.href);
          const acceptedUrls = new Set([observation.post_url]);
          const childObservations = typeof extractor.extractVisibleThreadDetails === "function"
            ? await extractor.extractVisibleThreadDetails(root, location.href, attemptedAt) : [];
          for (const child of childObservations) {
            const childResult = await sendMessage({ type: "SCE_OBSERVATION_READY", observation: child });
            if (childResult.accepted) acceptedUrls.add(child.post_url);
          }
          const observableNodes = nodes.filter((node) => acceptedUrls.has(node.post_url));
          if (Number.isInteger(result.observationId) && observableNodes.length > 0) {
            await sendMessage({
              type: "SCE_THREAD_SEQUENCE_READY",
              sequence: {
                root_post_url: observation.post_url,
                nodes: observableNodes.map((node) => ({
                  post_url: node.post_url,
                  sequence_position: node.sequence_position,
                  reply_to_post_url: node.reply_to_post_url,
                  same_author_as_root: node.same_author_as_root,
                  relationship_evidence: node.relationship_evidence,
                })),
                detail_observation_id: result.observationId,
                observed_at: attemptedAt,
                extractor_version: extractor.version,
              },
            });
          }
          renderThreadDiagnostic(root, button.parentElement || null, diagnostic);
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
    return button;
  }

  function createEngagementDiagnosticButton(root, pageUrl) {
    const extractor = scope.SCE_THREADS_POST_DETAIL_EXTRACTOR;
    const button = root.createElement("button");
    button.type = "button";
    button.setAttribute(ENGAGEMENT_DIAGNOSTIC_ATTRIBUTE, "true");
    button.textContent = "指標DOM診断";
    button.addEventListener("click", () => {
      const diagnostic = extractor.auditEngagementControls(root, pageUrl);
      let output = root.querySelector("[data-sce-engagement-diagnostic-output]");
      if (!output) {
        output = root.createElement("pre");
        output.setAttribute("data-sce-engagement-diagnostic-output", "true");
        output.style.cssText = "white-space:pre-wrap;font:12px/1.4 monospace;margin:8px;padding:8px;border:1px solid currentColor";
        button.parentElement.append(output);
      }
      output.textContent = "Engagement DOM診断: " + JSON.stringify(diagnostic);
    });
    return button;
  }

  function installActivityAction(root, pageUrl) {
    const extractor = scope.SCE_THREADS_POST_DETAIL_EXTRACTOR;
    for (const dialog of root.querySelectorAll('[role="dialog"], [aria-modal="true"]')) {
      if (dialog.querySelector("[" + ACTIVITY_BUTTON_ATTRIBUTE + "]")) continue;
      if (extractor.activityViewCount(dialog) === null) continue;
      const button = createActionButton(root, pageUrl, ACTIVITY_BUTTON_ATTRIBUTE, "詳細収集");
      button.style.cssText = "margin:8px;font:inherit;padding:6px 10px;border:1px solid currentColor;border-radius:999px;background:Canvas;color:CanvasText;cursor:pointer";
      dialog.append(button);
      return button;
    }
    return null;
  }

  function install(root = document, pageUrl = location.href) {
    const extractor = scope.SCE_THREADS_POST_DETAIL_EXTRACTOR;
    if (!extractor.recognizePostDetail(root, pageUrl)) return null;
    let cardButton = null;
    if (!root.querySelector("[" + BUTTON_ATTRIBUTE + "]")) {
      const canonicalPage = extractor.canonicalPostUrl(pageUrl, pageUrl);
      const anchor = Array.from(root.querySelectorAll('a[href*="/post/"]'))
        .filter(
          (link) => extractor.canonicalPostUrl(link.getAttribute("href"), pageUrl) === canonicalPage,
        )
        .map((link) => resolveDetailContainer(link))
        .find((candidate) => candidate !== null);
      if (anchor) {
        cardButton = createActionButton(root, pageUrl, BUTTON_ATTRIBUTE, "詳細収集");
        anchor.append(cardButton);
        anchor.append(createEngagementDiagnosticButton(root, pageUrl));
      }
    }
    return installActivityAction(root, pageUrl) || cardButton;
  }

  function observe(root = document, windowObject = window, Observer = MutationObserver) {
    let lastUrl = windowObject.location.href;
    const attempt = () => install(root, windowObject.location.href);
    const navigationAttempt = () => {
      if (windowObject.location.href !== lastUrl) {
        lastUrl = windowObject.location.href;
        attempt();
      }
    };
    const observer = new Observer(attempt);
    observer.observe(root.documentElement, { childList: true, subtree: true });
    windowObject.addEventListener("popstate", navigationAttempt);
    windowObject.addEventListener("hashchange", navigationAttempt);
    if (windowObject.navigation) windowObject.navigation.addEventListener("navigate", attempt);
    attempt();
    return () => {
      observer.disconnect();
      windowObject.removeEventListener("popstate", navigationAttempt);
      windowObject.removeEventListener("hashchange", navigationAttempt);
      if (windowObject.navigation) windowObject.navigation.removeEventListener("navigate", attempt);
    };
  }

  scope.SCE_DETAIL_ACTION = Object.freeze({
    install, observe, resolveDetailContainer, installActivityAction, renderThreadDiagnostic,
    createEngagementDiagnosticButton,
  });
})(globalThis);
