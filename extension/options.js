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
const selectAllCollected = document.querySelector("#select-all-collected");
const clearCollectedSelection = document.querySelector("#clear-collected-selection");
const requeueSelected = document.querySelector("#requeue-selected");
const requeueMissingEngagement = document.querySelector("#requeue-missing-engagement");
const collectedStatus = document.querySelector("#collected-status");
const collectedPosts = document.querySelector("#collected-posts");
const exportPostsCsv = document.querySelector("#export-posts-csv");
const exportThreadCsv = document.querySelector("#export-thread-csv");
const exportStatus = document.querySelector("#export-status");
const SAFE_PENDING_FAILURES = new Set([
  "network_error", "receiver_rejected", "invalid_receiver_response", "invalid_limit",
]);
const selectedPostUrls = new Set();
let visibleCollectedPosts = [];

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
    return Number.isInteger(post.display_views_normalized)
      ? post.display_views_normalized.toLocaleString("ja-JP") + "回"
      : String(post.display_views_raw).replace(/^表示\s*/, "");
  }
  if (post.rounded_views_raw !== null && post.rounded_views_raw !== undefined) {
    return String(post.rounded_views_raw).replace(/^表示\s*/, "");
  }
  return "未観測";
}

function updateSelectionControls() {
  requeueSelected.disabled = selectedPostUrls.size === 0;
  requeueSelected.textContent = selectedPostUrls.size
    ? `選択分を再補完対象にする（${selectedPostUrls.size}件）`
    : "選択分を再補完対象にする";
}

function renderCollectedPosts(posts) {
  collectedPosts.replaceChildren();
  for (const post of posts) {
    const row = document.createElement("tr");
    const select = document.createElement("td");
    select.className = "row-select";
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = selectedPostUrls.has(post.post_url);
    checkbox.setAttribute("aria-label", "投稿を再補完対象に選択");
    checkbox.addEventListener("change", () => {
      if (checkbox.checked) selectedPostUrls.add(post.post_url);
      else selectedPostUrls.delete(post.post_url);
      updateSelectionControls();
    });
    select.append(checkbox);
    row.append(select);
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
  updateSelectionControls();
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
    visibleCollectedPosts = response.posts;
    renderCollectedPosts(visibleCollectedPosts);
    collectedStatus.textContent = response.posts.length + "件を表示しています。";
  });
}

function updateDetailExclusion(action, postUrl) {
  return new Promise((resolve) => {
    chrome.runtime.sendMessage({
      type: "SCE_UPDATE_DETAIL_EXCLUSION", action, postUrl,
    }, (response) => {
      resolve(!chrome.runtime.lastError && response && response.accepted);
    });
  });
}

function updateCollectedPost(action, postUrl) {
  collectedStatus.textContent = action === "EXCLUDE" ? "除外を保存しています。" : "再補完を準備しています。";
  updateDetailExclusion(action, postUrl).then((accepted) => {
    if (!accepted) {
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
selectAllCollected.addEventListener("click", () => {
  for (const post of visibleCollectedPosts) selectedPostUrls.add(post.post_url);
  renderCollectedPosts(visibleCollectedPosts);
});
clearCollectedSelection.addEventListener("click", () => {
  selectedPostUrls.clear();
  renderCollectedPosts(visibleCollectedPosts);
});
requeueSelected.addEventListener("click", async () => {
  const urls = Array.from(selectedPostUrls);
  if (!urls.length) return;
  requeueSelected.disabled = true;
  collectedStatus.textContent = `${urls.length}件を再補完対象にしています。`;
  let completed = 0;
  for (const postUrl of urls) {
    if (await updateDetailExclusion("REQUEUE", postUrl)) completed += 1;
  }
  selectedPostUrls.clear();
  refreshQueueSummary();
  loadCollectedPosts();
  collectedStatus.textContent = completed === urls.length
    ? `${completed}件を再補完対象にしました。`
    : `${completed} / ${urls.length}件を再補完対象にしました。`;
});
requeueMissingEngagement.addEventListener("click", () => {
  requeueMissingEngagement.disabled = true;
  collectedStatus.textContent = "Like・返信・再投稿が未観測の投稿を確認しています。";
  chrome.runtime.sendMessage({ type: "SCE_REQUEUE_MISSING_ENGAGEMENT_METRICS" }, (response) => {
    requeueMissingEngagement.disabled = false;
    if (chrome.runtime.lastError || !response || !response.accepted) {
      collectedStatus.textContent = "指標未観測の再補完対象化に失敗しました。";
      return;
    }
    collectedStatus.textContent = `${response.count}件を指標再補完対象にしました。`;
    refreshQueueSummary();
    loadCollectedPosts();
  });
});
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
