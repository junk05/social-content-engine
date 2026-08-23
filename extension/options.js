"use strict";

const status = document.querySelector("#status");
const loadPending = document.querySelector("#load-pending");
const pendingStatus = document.querySelector("#pending-status");
const pendingDetails = document.querySelector("#pending-details");
const startDetailBatch = document.querySelector("#start-detail-batch");
const resumeDetailBatch = document.querySelector("#resume-detail-batch");
const batchStatus = document.querySelector("#batch-status");
const queueSummary = document.querySelector("#queue-summary");
const collectedFilter = document.querySelector("#collected-filter");
const collectedSort = document.querySelector("#collected-sort");
const refreshCollected = document.querySelector("#refresh-collected");
const collectedStatus = document.querySelector("#collected-status");
const collectedPosts = document.querySelector("#collected-posts");
const exportPostsCsv = document.querySelector("#export-posts-csv");
const exportThreadCsv = document.querySelector("#export-thread-csv");
const exportStatus = document.querySelector("#export-status");
const SAFE_PENDING_FAILURES = new Set([
  "network_error", "receiver_rejected", "invalid_receiver_response", "invalid_limit",
]);

chrome.runtime.sendMessage({ type: "SCE_SCAFFOLD_STATUS" }, (response) => {
  if (chrome.runtime.lastError || !response) {
    status.textContent = "スケルトン状態を確認できませんでした。";
    return;
  }
  status.textContent = response.stage + ": " + (response.ready ? "送信準備済み" : "未接続");
});

function refreshQueueSummary() {
  chrome.runtime.sendMessage({ type: "SCE_DETAIL_QUEUE_STATUS" }, (response) => {
    if (chrome.runtime.lastError || !response || !response.accepted || !response.counts) {
      queueSummary.textContent = "詳細queueを確認できませんでした。";
      return;
    }
    queueSummary.textContent = [
      `収集済み: ${response.collectedCount}`,
      `DETAIL_PENDING: ${response.counts.DETAIL_PENDING}`,
      `DETAIL_PROCESSING: ${response.counts.DETAIL_PROCESSING}`,
      `DETAIL_ENRICHED: ${response.counts.DETAIL_ENRICHED}`,
      `DETAIL_FAILED: ${response.counts.DETAIL_FAILED}`,
      `除外: ${response.excludedCount || 0}`,
    ].join(" / ");
  });
}

refreshQueueSummary();

function postCell(post) {
  const cell = document.createElement("td");
  const link = document.createElement("a");
  link.href = post.post_url;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  link.textContent = "@" + post.author_username;
  const meta = document.createElement("span");
  meta.className = "post-meta";
  meta.textContent = post.collected_at + "\n" + post.post_url;
  cell.append(link);
  cell.append(meta);
  return cell;
}

function valueOrUnknown(value) {
  return value === null || value === undefined ? "未観測" : String(value);
}

function visibleViews(post) {
  if (post.display_views_raw !== null && post.display_views_raw !== undefined) {
    return valueOrUnknown(post.display_views_raw) + "（正確表示）";
  }
  if (post.rounded_views_raw !== null && post.rounded_views_raw !== undefined) {
    return valueOrUnknown(post.rounded_views_raw) + "（概算）";
  }
  return "未観測";
}

function renderCollectedPosts(posts) {
  collectedPosts.replaceChildren();
  for (const post of posts) {
    const row = document.createElement("tr");
    row.append(postCell(post));
    const state = document.createElement("td");
    state.textContent = post.detail_status
      + (post.last_error ? "\n" + post.last_error : "")
      + "\n試行: " + post.attempt_count;
    row.append(state);
    const metrics = document.createElement("td");
    metrics.textContent = "Views: " + visibleViews(post)
      + "\nSelf replies: " + valueOrUnknown(post.self_reply_count);
    row.append(metrics);
    const actions = document.createElement("td");
    actions.className = "row-actions";
    const requeue = document.createElement("button");
    requeue.type = "button";
    requeue.textContent = "再補完";
    requeue.addEventListener("click", () => updateCollectedPost("REQUEUE", post.post_url));
    const exclude = document.createElement("button");
    exclude.type = "button";
    exclude.textContent = post.enrichment_excluded ? "除外済み" : "詳細補完対象から除外";
    exclude.disabled = post.enrichment_excluded;
    exclude.addEventListener("click", () => updateCollectedPost("EXCLUDE", post.post_url));
    actions.append(requeue);
    actions.append(exclude);
    row.append(actions);
    collectedPosts.append(row);
  }
}

function loadCollectedPosts() {
  refreshCollected.disabled = true;
  collectedStatus.textContent = "収集済み投稿を読み込んでいます。";
  chrome.runtime.sendMessage({
    type: "SCE_LIST_COLLECTED_POSTS",
    status: collectedFilter.value || "ALL",
    sort: collectedSort.value || "newest",
    limit: 200,
  }, (response) => {
    refreshCollected.disabled = false;
    if (chrome.runtime.lastError || !response || !response.accepted
        || !Array.isArray(response.posts)) {
      collectedPosts.replaceChildren();
      collectedStatus.textContent = "収集済み投稿を読み込めませんでした。";
      return;
    }
    renderCollectedPosts(response.posts);
    collectedStatus.textContent = response.posts.length + "件を表示しています。";
  });
}

function updateCollectedPost(action, postUrl) {
  collectedStatus.textContent = action === "EXCLUDE" ? "除外を保存しています。" : "再補完を準備しています。";
  chrome.runtime.sendMessage({
    type: "SCE_UPDATE_DETAIL_EXCLUSION", action, postUrl,
  }, (response) => {
    if (chrome.runtime.lastError || !response || !response.accepted) {
      collectedStatus.textContent = "操作を保存できませんでした。";
      return;
    }
    refreshQueueSummary();
    loadCollectedPosts();
  });
}

refreshCollected.addEventListener("click", loadCollectedPosts);
collectedFilter.addEventListener("change", loadCollectedPosts);
collectedSort.addEventListener("change", loadCollectedPosts);
loadCollectedPosts();

function runReviewExport(kind, button) {
  button.disabled = true;
  exportStatus.textContent = "CSVを生成しています。";
  SCE_REVIEW_EXPORT_DOWNLOAD.download(kind, collectedFilter.value || "ALL")
    .then((result) => {
      exportStatus.textContent = result.accepted
        ? result.filename + "を保存しました。"
        : "CSVを保存できませんでした。";
    })
    .catch(() => { exportStatus.textContent = "CSVを保存できませんでした。"; })
    .finally(() => { button.disabled = false; });
}

exportPostsCsv.addEventListener("click", () => runReviewExport("POSTS", exportPostsCsv));
exportThreadCsv.addEventListener(
  "click", () => runReviewExport("THREAD_NODES", exportThreadCsv),
);

chrome.runtime.onMessage.addListener((message) => {
  if (!message || message.type !== "SCE_DETAIL_BATCH_PROGRESS" || !message.progress) {
    return false;
  }
  const progress = message.progress;
  const total = Number.isInteger(progress.total) ? progress.total : "?";
  const base = `${progress.processed || 0} / ${total}件 `
    + `(成功 ${progress.succeeded || 0} / 失敗 ${progress.failed || 0})`;
  batchStatus.textContent = progress.status === "WAITING_NEXT_ITEM"
    ? `${base} — 次の投稿まで待機中`
    : `${base} — 詳細を処理中`;
  return false;
});

loadPending.addEventListener("click", () => {
  loadPending.disabled = true;
  pendingStatus.textContent = "詳細待ちを読み込んでいます。";
  chrome.runtime.sendMessage(
    { type: "SCE_LOAD_PENDING_DETAILS", limit: 50 },
    (response) => {
      loadPending.disabled = false;
      pendingDetails.replaceChildren();
      if (chrome.runtime.lastError || !response || !response.accepted) {
        const reason = response && SAFE_PENDING_FAILURES.has(response.reason)
          ? ` (${response.reason})` : "";
        const statusCode = response && response.reason === "receiver_rejected"
          && Number.isInteger(response.status) ? ` [HTTP ${response.status}]` : "";
        pendingStatus.textContent = "詳細待ちを読み込めませんでした。" + reason + statusCode;
        return;
      }
      pendingStatus.textContent = response.urls.length + "件の詳細待ちがあります。";
      for (const url of response.urls) {
        const item = document.createElement("li");
        const link = document.createElement("a");
        link.href = url;
        link.textContent = url;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        item.append(link);
        pendingDetails.append(item);
      }
    },
  );
});

function runDetailBatch(type) {
  startDetailBatch.disabled = true;
  resumeDetailBatch.disabled = true;
  batchStatus.textContent = "詳細バッチを実行しています。";
  chrome.runtime.sendMessage({ type, limit: 50 }, (response) => {
    startDetailBatch.disabled = false;
    resumeDetailBatch.disabled = false;
    if (chrome.runtime.lastError || !response || !response.accepted) {
      batchStatus.textContent = "詳細バッチを完了できませんでした。再開できます。";
      return;
    }
    const results = response.state && Array.isArray(response.state.results)
      ? response.state.results : [];
    const counts = response.counts || {};
    batchStatus.textContent = `詳細補完完了: ${counts.DETAIL_ENRICHED || results.length}件`;
    refreshQueueSummary();
  });
}

startDetailBatch.addEventListener("click", () => runDetailBatch("SCE_START_DETAIL_BATCH"));
resumeDetailBatch.addEventListener("click", () => runDetailBatch("SCE_RESUME_DETAIL_BATCH"));
