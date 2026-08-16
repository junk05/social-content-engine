# Social Content Engine

Threads分析ツール chatgpt

M0 collects and preserves public Threads posts through Meta's official API. It
does not generate or publish content.

## Local verification

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
PATH=".venv/bin:$PATH" sh scripts/check.sh
```

## Browser ingestion receiver

Chromeの拡張機能管理画面（`chrome://extensions`）で、unpacked extensionの
32文字の拡張機能IDを確認します。実際のIDはファイルへ書いたりcommitしたりせず、
起動するshellだけでorigin allowlistへ設定してください。

```bash
export SCE_BROWSER_EXTENSION_ORIGINS='chrome-extension://<32-char-id>'
.venv/bin/sce-browser-ingest \
  --database data/browser-ingest.sqlite3 \
  --host 127.0.0.1 \
  --port 8765
```

receiverは`http://127.0.0.1:8765/browser-ingest/threads`で待機します。SQLite
databaseはgit ignoredの`data/`配下へ保存してください。このreceiverにAPI token、
cookie、passwordなどのsecretは不要です。localhost専用なので、外部tunnelは不要であり、
使用しないでください。

## HG-01: live Threads API spike

Required credential: a Threads user access token granted through a Meta App's
Threads use case with at least `threads_basic` and `threads_keyword_search`.
Create/configure the app in the [Meta App Dashboard](https://developers.facebook.com/apps/)
and complete the documented Threads OAuth authorization-code flow. Add
`threads_profile_discovery` or `threads_read_replies` only for the corresponding
later spikes.

Set the token only in the shell environment, then execute one low-volume request:

```bash
export THREADS_ACCESS_TOKEN='...'
.venv/bin/sce-threads-spike --query '恋愛' --search-type RECENT --limit 5
```

The command stores the exact response body under ignored `data/raw/` and in the
SQLite collection run, then derives normalized posts. Access tokens are excluded
from stored request provenance.

## Meta callback server

The framework-free callback server provides the three URLs required by the Meta
App dashboard. It is intended only for the M0 authorization setup.

Generate a one-time OAuth state and configure secrets in the current shell. Do
not paste or commit the App Secret.

```bash
export THREADS_APP_SECRET='Threads App Secret from Meta'
export META_OAUTH_STATE="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
export META_PUBLIC_BASE_URL='https://your-temporary-tunnel-host.example'
export META_CALLBACK_HOST='127.0.0.1'
export META_CALLBACK_PORT='8787'
.venv/bin/sce-meta-callbacks
```

Expose `http://127.0.0.1:8787` through a temporary HTTPS tunnel. For example, if
`cloudflared` is already installed:

```bash
cloudflared tunnel --url http://127.0.0.1:8787
```

Restart the server after setting `META_PUBLIC_BASE_URL` to the HTTPS origin shown
by the tunnel. Register these exact URLs in Meta:

```text
OAuth Redirect Callback URL:
https://<tunnel-host>/meta/oauth/callback

Deauthorization Callback URL:
https://<tunnel-host>/meta/deauthorization

Data Deletion Request URL:
https://<tunnel-host>/meta/data-deletion
```

For OAuth authorization, pass the same callback URL as `redirect_uri` and pass
the current `META_OAUTH_STATE` as `state`. The callback verifies state and leaves
the authorization code visible in the browser URL without saving or logging it.
When exchanging the code at `https://graph.threads.net/oauth/access_token`, use
the identical `redirect_uri`.

The deletion response points to:

```text
https://<tunnel-host>/meta/data-deletion/status?code=<confirmation_code>
```

See [the callback contract](spec/META_CALLBACKS.md) for methods, parameters,
responses, and signature verification rules.

## M1 deterministic Analyzer

Analyze a post already present in the normalized SQLite store. M1 defaults to
the deterministic local adapter: it makes no paid API call and requires no model
credential.

```bash
.venv/bin/sce-analyze --database data/social_content.sqlite3 --post-id '<source_post_id>'
```

An identical successful run is replayed by default. To preserve a fresh,
versioned analysis run instead:

```bash
.venv/bin/sce-analyze \
  --database data/social_content.sqlite3 \
  --post-id '<source_post_id>' \
  --force
```

Only normalized M0 data is read. Analyzer runs and validated output are appended
to `analysis_runs` and `post_analysis`; raw and normalized evidence is not
rewritten. See [the M1 contract](spec/M1_ANALYZER.md).

## M2 bounded collection

Run a credential-safe, resumable TOP/RECENT batch. Exact response bodies,
collection-run provenance, normalized versions, checkpoints, and the summary
report stay under ignored local `data/` paths.

```bash
export THREADS_ACCESS_TOKEN='...'
.venv/bin/sce-threads-batch \
  --query '恋愛' --query '人間関係' --query '心理' --query '美容' --query '仕事' \
  --search-type RECENT --search-type TOP \
  --page-limit 25 --max-requests 10 --target-unique 100 --hard-cap 200
```

Live requests are sequential with a minimum two-second interval. Empty pages,
repeated cursors, request caps, HTTP errors, and malformed responses are explicit
stop reasons; unavailable results or metrics are never fabricated.
