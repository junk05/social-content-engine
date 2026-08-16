"use strict";

const status = document.querySelector("#status");
chrome.runtime.sendMessage({ type: "SCE_SCAFFOLD_STATUS" }, (response) => {
  if (chrome.runtime.lastError || !response) {
    status.textContent = "スケルトン状態を確認できませんでした。";
    return;
  }
  status.textContent = `${response.stage}: ${response.ready ? "送信準備済み" : "未接続"}`;
});
