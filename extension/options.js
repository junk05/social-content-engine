"use strict";

const status = document.querySelector("#status");
const loadPending = document.querySelector("#load-pending");
const pendingStatus = document.querySelector("#pending-status");
const pendingDetails = document.querySelector("#pending-details");

chrome.runtime.sendMessage({ type: "SCE_SCAFFOLD_STATUS" }, (response) => {
  if (chrome.runtime.lastError || !response) {
    status.textContent = "スケルトン状態を確認できませんでした。";
    return;
  }
  status.textContent = response.stage + ": " + (response.ready ? "送信準備済み" : "未接続");
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
        pendingStatus.textContent = "詳細待ちを読み込めませんでした。";
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
