# Threads Collector extension scaffold

Manifest V3 unpacked extensionです。M3-005では、明示的に渡されたThreads検索
カード1件から公開表示フィールドだけを読むversioned extractorを追加しました。
`Pattern収集`ボタン、MutationObserver、localhostへの送信は行いません。これらは
M3-006で実装・検証します。

## ローカルで読み込む手順

実ブラウザへの読み込みはHG-03の承認後に、人が操作して行います。

1. Chrome系ブラウザで `chrome://extensions` を開きます。
2. 「デベロッパーモード」を有効にします。
3. 「パッケージ化されていない拡張機能を読み込む」を選びます。
4. この `extension/` フォルダを指定します。
5. 拡張機能の詳細からオプション画面を開き、`M3-005: receiver未接続`を確認します。

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
```
