# Threads Collector extension scaffold

Manifest V3 unpacked extensionです。M3-006では、認識済みThreads検索カードへの
`Pattern収集`ボタン、bounded/debounced MutationObserver、SPA URL変更時の再scanを
追加しました。M3-007では、人がbuttonを押して生成した観測だけを
`http://127.0.0.1:8765/browser-ingest/threads`へ送信します。

## ローカルで読み込む手順

実ブラウザへの読み込みはHG-03の承認後に、人が操作して行います。

1. Chrome系ブラウザで `chrome://extensions` を開きます。
2. 「デベロッパーモード」を有効にします。
3. 「パッケージ化されていない拡張機能を読み込む」を選びます。
4. この `extension/` フォルダを指定します。
5. root READMEの手順でloopback receiverを起動します。
6. 拡張機能の詳細からオプション画面を開き、送信準備済み表示を確認します。
7. Threads検索カードの`Pattern収集`は、人が押したカードだけを保存します。
   保存に成功した投稿のcanonical URLだけは拡張機能のローカルストレージへ記録され、
   再読み込み後も`✓ 収集済み`として復元されます。本文・cookie・tokenは保存しません。
8. オプション画面の「詳細待ちを読み込む」でURLを確認し、人がリンクを開いて、
   detail pageの「詳細収集」を押します。拡張機能は自動でページを開きません。

Chrome Web Store公開、ビルドツール、パッケージ化、自動更新は対象外です。

## セキュリティ境界

- Threadsの表示中ページにだけcontent scriptを配置します。
- localhost権限はloopback IPv4のHTTP originだけです。
- パスワード、cookie、access tokenを要求・取得・保存しません。
- Chromeの`storage`権限は、保存成功済みのcanonical投稿URLだけの復元表示に使用します。
- 自動検索、スクロール、ナビゲーション、DOM dumpを行いません。
- 外部サイトや公開receiverへデータを送信しません。

## 静的検証

```bash
python3 -m unittest discover -s extension/tests -v
node extension/tests/extractor_test.js
node extension/tests/injection_test.js
node extension/tests/transport_test.js
node extension/tests/detail_extractor_test.js
node extension/tests/detail_action_test.js
node extension/tests/options_test.js
```
