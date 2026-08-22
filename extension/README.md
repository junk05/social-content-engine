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
8. オプション画面のqueue件数を確認し、「詳細をまとめて補完」を1回押します。
   拡張機能は`Pattern収集`済みの`DETAIL_PENDING`だけを、専用の非activeタブ1枚で
   直列処理します。通常利用中のThreadsタブは遷移させません。
9. Chromeや拡張機能が中断した場合は「中断した詳細補完を再開」を押します。
   Source Storeのleaseを回収して再試行し、古いworker応答は受理しません。

## 収集済み投稿一覧

オプション画面の`収集済み投稿一覧`は、loopback Source Storeにあるcanonical
rootだけをローカル表示します。状態filterで絞り込み、`再補完`で明示的に
`DETAIL_PENDING`へ戻すか、`詳細補完対象から除外`でqueue対象外にできます。
除外は物理削除ではありません。既存の投稿、metrics、attempt、failure、Thread
evidenceは保持され、操作履歴も追記されます。除外済み投稿は`再補完`で再有効化
できます。

`投稿一覧CSV`と`Thread Sequence CSV`は、現在選択中の状態filterを使って
loopback receiverの既存Human Review exporterを呼び出します。CSVは日本語対応の
UTF-8 BOMでChromeから保存され、DBや`data/exports`を変更しません。CSV生成処理は
Extension側に持たず、source textはHuman Review用の`ANALYSIS_ONLY_SOURCE`としてのみ
含まれます。

## 終了済み診断機能

M4-FU01-S1〜S5で使用したActivity、macOS native input helper、座標校正の
1投稿限定診断は通常運用に不要なため、オプション画面には表示しません。検証済みの
内部実装、回帰test、SSOT、技術証跡は監査と将来の再評価のため保持します。
Detail Enrichmentの必須経路はdetail page上の本文、Rounded Views、Thread Sequenceで、
Activity sheetやmacOS Accessibility permissionには依存しません。

Chrome Web Store公開、ビルドツール、パッケージ化、自動更新は対象外です。

## セキュリティ境界

- Threadsの表示中ページにだけcontent scriptを配置します。
- localhost権限はloopback IPv4のHTTP originだけです。
- パスワード、cookie、access tokenを要求・取得・保存しません。
- Chromeの`storage`権限は、保存成功済みcanonical投稿URLとbatch/tabの再開hintだけに
  使用します。本文や認証情報は保存しません。
- Chromeの`tabs`権限は、明示開始後の専用detail tab 1枚の作成・再利用・閉鎖だけに
  使用します。検索、選別、scroll、通常タブの遷移には使用しません。
- Native Input Spikeのlocal helperはreceiverだけが一度だけ起動できます。任意座標、
  keyboard、clipboard、任意コマンドを受け付けるAPIは提供しません。
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
node extension/tests/native_input_probe_test.js
node extension/tests/detail_batch_worker_test.js
node extension/tests/batch_controller_test.js
```
