"use strict";

const status = document.querySelector("#status");
const loadPending = document.querySelector("#load-pending");
const pendingStatus = document.querySelector("#pending-status");
const pendingDetails = document.querySelector("#pending-details");
const startDetailBatch = document.querySelector("#start-detail-batch");
const resumeDetailBatch = document.querySelector("#resume-detail-batch");
const batchStatus = document.querySelector("#batch-status");
const queueSummary = document.querySelector("#queue-summary");
const runDebuggerSpike = document.querySelector("#run-debugger-spike");
const debuggerSpikeStatus = document.querySelector("#debugger-spike-status");
const runDebuggerForegroundSpike = document.querySelector("#run-debugger-foreground-spike");
const debuggerForegroundSpikeStatus = document.querySelector("#debugger-foreground-spike-status");
const runNativeInputSpike = document.querySelector("#run-native-input-spike");
const nativeInputSpikeStatus = document.querySelector("#native-input-spike-status");
const runNativeInputDiagnostic = document.querySelector("#run-native-input-diagnostic");
const nativeInputDiagnosticStatus = document.querySelector("#native-input-diagnostic-status");
const runNativeCursorCalibration = document.querySelector("#run-native-cursor-calibration");
const nativeCursorCalibrationStatus = document.querySelector("#native-cursor-calibration-status");
const collectedFilter = document.querySelector("#collected-filter");
const collectedSort = document.querySelector("#collected-sort");
const refreshCollected = document.querySelector("#refresh-collected");
const collectedStatus = document.querySelector("#collected-status");
const collectedPosts = document.querySelector("#collected-posts");
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
    metrics.textContent = "Views: " + valueOrUnknown(post.rounded_views_raw)
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

runDebuggerSpike.addEventListener("click", () => {
  runDebuggerSpike.disabled = true;
  debuggerSpikeStatus.textContent = "選択済みの詳細待ち投稿1件でActivity表示を検証しています。";
  chrome.runtime.sendMessage({ type: "SCE_START_DEBUGGER_ACTIVITY_SPIKE" }, (response) => {
    runDebuggerSpike.disabled = false;
    if (chrome.runtime.lastError || !response) {
      debuggerSpikeStatus.textContent = "Activity表示を検証できませんでした。";
      return;
    }
    const messages = {
      SHEET_OBSERVED: "Activity sheetの表示を確認しました。",
      SHEET_NOT_OBSERVED: "Activity sheetの表示を確認できませんでした。",
      TARGET_NOT_FOUND: "Activityボタンを確認できませんでした。",
      DEBUGGER_ATTACH_FAILED: "Activity表示を検証できませんでした。",
      DEBUGGER_COMMAND_FAILED: "Activity表示を検証できませんでした。",
      TAB_UNAVAILABLE: "検証できる詳細待ち投稿を確認できませんでした。",
    };
    debuggerSpikeStatus.textContent = messages[response.outcome] || "Activity表示を検証できませんでした。";
  });
});

runDebuggerForegroundSpike.addEventListener("click", () => {
  runDebuggerForegroundSpike.disabled = true;
  debuggerForegroundSpikeStatus.textContent = "詳細投稿を前面化してActivity表示を検証しています。";
  chrome.runtime.sendMessage({ type: "SCE_START_DEBUGGER_FOREGROUND_SPIKE" }, (response) => {
    runDebuggerForegroundSpike.disabled = false;
    if (chrome.runtime.lastError || !response) {
      debuggerForegroundSpikeStatus.textContent = "Activity表示を検証できませんでした。";
      return;
    }
    const messages = {
      SHEET_OBSERVED: "Activity sheetの表示を確認しました。",
      SHEET_NOT_OBSERVED_FOREGROUND: "前面化後もActivity sheetの表示を確認できませんでした。",
      TARGET_NOT_FOUND: "Activityボタンを確認できませんでした。",
      DEBUGGER_ATTACH_FAILED: "Activity表示を検証できませんでした。",
      DEBUGGER_COMMAND_FAILED: "Activity表示を検証できませんでした。",
      TAB_UNAVAILABLE: "検証できる詳細待ち投稿を確認できませんでした。",
    };
    debuggerForegroundSpikeStatus.textContent = messages[response.outcome] || "Activity表示を検証できませんでした。";
  });
});
runNativeInputSpike.addEventListener("click", () => {
  runNativeInputSpike.disabled = true;
  nativeInputSpikeStatus.textContent = "macOS実マウス入力を検証しています。";
  chrome.runtime.sendMessage({ type: "SCE_START_NATIVE_INPUT_SPIKE" }, (response) => {
    runNativeInputSpike.disabled = false;
    const labels = {
      NATIVE_INPUT_DETAIL_ENRICHED: "Activity sheet・取得可能metrics・DETAIL_ENRICHEDを確認しました。",
      NATIVE_INPUT_VIEW_NOT_EXTRACTED: "Activity sheetは開きましたが閲覧数を抽出できませんでした。",
      NATIVE_INPUT_INGESTION_FAILED: "閲覧数は抽出しましたがreceiverへ保存できませんでした。",
      NATIVE_INPUT_SHEET_NOT_OBSERVED: "Activity sheetの表示を確認できませんでした。",
      ACCESSIBILITY_PERMISSION_REQUIRED: "macOSのアクセシビリティ許可が必要です。",
      TARGET_NOT_FOUND: "Activityボタンを確認できませんでした。",
    };
    nativeInputSpikeStatus.textContent = labels[response && response.outcome] || "macOS実マウス入力を検証できませんでした。";
    if (response && response.viewObservationStatus) {
      nativeInputSpikeStatus.textContent += "\nview_count: " + response.viewObservationStatus;
    }
    if (response && response.extractionFailure) {
      nativeInputSpikeStatus.textContent += "\n抽出段階: " + response.extractionFailure;
    }
    if (response && response.postDetailReadiness) {
      nativeInputSpikeStatus.textContent += "\n投稿DOM: "
        + JSON.stringify(response.postDetailReadiness);
    }
    if (response && response.diagnostics) {
      nativeInputSpikeStatus.textContent += "\nDOM診断: " + JSON.stringify(response.diagnostics);
    }
  });
});
runNativeInputDiagnostic.addEventListener("click", () => {
  chrome.runtime.sendMessage({ type: "SCE_RUN_NATIVE_INPUT_DIAGNOSTIC" }, (response) => {
    nativeInputDiagnosticStatus.textContent = response && response.outcome === "accessibility_allowed" ? "HELPER_LAUNCH_OK / ACCESSIBILITY_ALLOWED / BRIDGE_OK" : "helper診断に失敗しました。";
  });
});
runNativeCursorCalibration.addEventListener("click", () => {
  runNativeCursorCalibration.disabled = true;
  nativeCursorCalibrationStatus.textContent = "対象位置へカーソルだけを移動しています。";
  chrome.runtime.sendMessage({ type: "SCE_START_NATIVE_CURSOR_CALIBRATION" }, (response) => {
    runNativeCursorCalibration.disabled = false;
    const labels = {
      CURSOR_MOVE_SENT: "カーソル位置を画面で確認してください。クリックは実行していません。",
      TARGET_NOT_FOUND: "Activityボタンの位置を確認できませんでした。",
      ACCESSIBILITY_PERMISSION_REQUIRED: "macOSのアクセシビリティ許可が必要です。",
      COORDINATE_OUT_OF_DISPLAY_BOUNDS: "計算した位置が画面範囲外でした。",
      CURSOR_POSITION_MISMATCH: "計算位置へカーソルを移動できませんでした。",
      CALIBRATION_ALREADY_CONSUMED: "このreceiverでは校正を実行済みです。",
    };
    nativeCursorCalibrationStatus.textContent = labels[response && response.outcome]
      || "カーソル位置を検証できませんでした。";
    if (response && response.outcome === "CURSOR_MOVE_SENT" && response.diagnostics) {
      nativeCursorCalibrationStatus.textContent += "\n診断値: "
        + JSON.stringify(response.diagnostics);
    }
  });
});
