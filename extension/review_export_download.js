"use strict";

(function exposeReviewExportDownload(scope) {
  const EXPORT_URL = "http://127.0.0.1:8765/browser-ingest/threads/review-export";
  const KINDS = Object.freeze({
    POSTS: "threads_posts.csv",
    THREAD_NODES: "threads_thread_nodes.csv",
  });
  const STATUSES = new Set([
    "ALL", "DETAIL_PENDING", "DETAIL_FAILED", "DETAIL_ENRICHED", "EXCLUDED",
  ]);

  async function download(kind, status = "ALL", options = {}) {
    if (!(kind in KINDS) || !STATUSES.has(status)) {
      return { accepted: false, reason: "invalid_export_request" };
    }
    const extensionId = chrome.runtime && chrome.runtime.id;
    if (typeof extensionId !== "string" || !/^[a-p]{32}$/.test(extensionId)) {
      return { accepted: false, reason: "extension_origin_unavailable" };
    }
    const fetchImpl = options.fetch || fetch;
    const documentImpl = options.document || document;
    const urlApi = options.urlApi || URL;
    const setTimer = options.setTimeout || setTimeout;
    const endpoint = EXPORT_URL + "?kind=" + encodeURIComponent(kind)
      + "&status=" + encodeURIComponent(status);
    try {
      const response = await fetchImpl(endpoint, {
        method: "GET",
        headers: { "X-SCE-Extension-Origin": "chrome-extension://" + extensionId },
        cache: "no-store",
        credentials: "omit",
      });
      if (response.status !== 200
          || !String(response.headers.get("Content-Type") || "").startsWith("text/csv")) {
        return { accepted: false, reason: "receiver_rejected", status: response.status };
      }
      const blob = await response.blob();
      const objectUrl = urlApi.createObjectURL(blob);
      const anchor = documentImpl.createElement("a");
      anchor.href = objectUrl;
      anchor.download = KINDS[kind];
      anchor.click();
      setTimer(() => urlApi.revokeObjectURL(objectUrl), 0);
      return { accepted: true, filename: KINDS[kind] };
    } catch (_error) {
      return { accepted: false, reason: "network_error" };
    }
  }

  scope.SCE_REVIEW_EXPORT_DOWNLOAD = Object.freeze({ EXPORT_URL, download });
})(globalThis);
