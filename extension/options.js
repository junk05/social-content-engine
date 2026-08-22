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
    ].join(" / ");
  });
}

refreshQueueSummary();

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
