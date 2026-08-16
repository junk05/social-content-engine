# Threads Collector extension scaffold

Manifest V3 unpacked extensionです。M3-006では、認識済みThreads検索カードへの
`Pattern収集`ボタン、bounded/debounced MutationObserver、SPA URL変更時の再scanを
追加しました。観測生成は人がbuttonを押したときだけです。localhostへの送信は
まだ行いません。

## ローカルで読み込む手順

実ブラウザへの読み込みはHG-03の承認後に、人が操作して行います。

1. Chrome系ブラウザで `chrome://extensions` を開きます。
2. 「デベロッパーモード」を有効にします。
3. 「パッケージ化されていない拡張機能を読み込む」を選びます。
4. この `extension/` フォルダを指定します。
5. 拡張機能の詳細からオプション画面を開き、`M3-006: receiver未接続`を確認します。

Chrome Web Store公開、ビルドツール、パッケージ化、自動更新は対象外です。

## セキュリティ境界

- Threadsの表示中ページにだけcontent scriptを配置します。
- localhost権限はloopback IPv4のHTTP originだけです。
- パスワード、cookie、access tokenを要求・取得・保存しません。
- 自動検索、スクロール、ナビゲーション、DOM dumpを行いません。
- 外部サイトや公開receiverへデータを送信しません。

## 静的検証

```bash
python3 -m unittest discover -s extension/tests -v
node extension/tests/extractor_test.js
node extension/tests/injection_test.js
```
