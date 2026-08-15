# Social Content Engine

M0 collects and preserves public Threads posts through Meta's official API. It
does not generate or publish content.

## Local verification

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
PATH=".venv/bin:$PATH" sh scripts/check.sh
```

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
