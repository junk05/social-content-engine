"""CLI for one explicit, low-volume keyword search spike."""

import argparse
import hashlib
import os
import sys
from pathlib import Path
from typing import Sequence

from social_content_engine import __version__
from social_content_engine.data.pipeline import ingest_response
from social_content_engine.data.repository import Repository

from .client import ThreadsClient

DEFAULT_FIELDS = "id,media_type,permalink,owner,username,text,timestamp"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", required=True, help="Keyword to search")
    parser.add_argument("--search-type", choices=["TOP", "RECENT"], default="RECENT")
    parser.add_argument("--fields", default=DEFAULT_FIELDS)
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--after", default="", help="Opaque cursor returned by the API")
    parser.add_argument("--database", type=Path, default=Path("data/social_content.sqlite3"))
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw"))
    return parser


def main(argv: Sequence[str] = ()) -> int:
    args = build_parser().parse_args(argv or None)
    token = os.environ.get("THREADS_ACCESS_TOKEN", "")
    if not token:
        print("HG-01: set THREADS_ACCESS_TOKEN before running the live spike", file=sys.stderr)
        return 2
    if args.limit < 1 or args.limit > 100:
        print("--limit must be between 1 and 100", file=sys.stderr)
        return 2

    client = ThreadsClient(token)
    capture = client.keyword_search(
        query=args.query,
        search_type=args.search_type,
        fields=args.fields,
        limit=args.limit,
        after=args.after,
    )
    args.raw_dir.mkdir(parents=True, exist_ok=True)
    args.database.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(capture.body).hexdigest()
    raw_path = args.raw_dir / (digest + ".json")
    raw_path.write_bytes(capture.body)

    if capture.status < 200 or capture.status >= 300:
        print("Threads API returned HTTP " + str(capture.status), file=sys.stderr)
        print("Raw error response saved to " + str(raw_path), file=sys.stderr)
        return 1

    with Repository(args.database) as repository:
        posts = ingest_response(
            repository,
            endpoint=capture.endpoint,
            request={"params": capture.request_params},
            started_at=capture.started_at,
            completed_at=capture.completed_at,
            http_status=capture.status,
            response_headers=capture.headers,
            raw_response=capture.body,
            collector_version=__version__,
        )
    print("Stored " + str(len(posts)) + " normalized post(s); raw=" + str(raw_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
