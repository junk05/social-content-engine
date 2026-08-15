"""Persist and run bounded M2 keyword-search collection plans."""

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional, Sequence

from social_content_engine import __version__
from social_content_engine.data.pipeline import derive_posts_from_response
from social_content_engine.data.repository import Repository

from .client import HttpCapture, ThreadsClient
from .paginator import CollectionPlan, SearchJob, collect, summary_json
from .spike import DEFAULT_FIELDS

DEFAULT_QUERIES = ("恋愛", "人間関係", "心理", "美容", "仕事")


def _utc_now_compact() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


class BatchCapturePersister:
    """Persist exact captures and link them to their ordered batch queries."""

    def __init__(
        self,
        repository: Repository,
        batch_query_ids: Dict[SearchJob, int],
        raw_dir: Path,
    ) -> None:
        self.repository = repository
        self.batch_query_ids = batch_query_ids
        self.raw_dir = raw_dir

    def __call__(self, job: SearchJob, capture: HttpCapture, _ordinal: int) -> None:
        digest = hashlib.sha256(capture.body).hexdigest()
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        (self.raw_dir / (digest + ".json")).write_bytes(capture.body)
        run_id = self.repository.add_collection_run(
            endpoint=capture.endpoint,
            request={"params": capture.request_params},
            started_at=capture.started_at,
            completed_at=capture.completed_at,
            http_status=capture.status,
            response_headers=capture.headers,
            raw_response=capture.body,
            raw_response_sha256=digest,
            collector_version=__version__,
        )
        self.repository.link_collection_run(self.batch_query_ids[job], run_id)
        if 200 <= capture.status < 300:
            try:
                derive_posts_from_response(
                    self.repository,
                    collection_run_id=run_id,
                    raw_response=capture.body,
                    completed_at=capture.completed_at,
                )
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
                return


def run_collection_batch(
    repository: Repository,
    client: ThreadsClient,
    plan: CollectionPlan,
    *,
    batch_key: str,
    raw_dir: Path,
    checkpoint_path: Optional[Path] = None,
    resume: bool = False,
) -> Dict[str, object]:
    config = {
        "queries": list(plan.queries),
        "search_types": list(plan.search_types),
        "search_mode": plan.search_mode,
        "fields": plan.fields,
        "since": plan.since,
        "until": plan.until,
        "page_limit": plan.page_limit,
        "target_unique": plan.target_unique,
        "hard_cap": plan.hard_cap,
        "max_requests": plan.max_requests,
        "live_interval_seconds": plan.live_interval_seconds,
    }
    batch_id = repository.create_collection_batch(batch_key, config, __version__)
    query_ids: Dict[SearchJob, int] = {}
    for ordinal, job in enumerate(plan.jobs()):
        query_ids[job] = repository.add_collection_batch_query(
            batch_id,
            ordinal,
            {
                "q": job.query,
                "search_type": job.search_type,
                "search_mode": plan.search_mode,
                "fields": plan.fields,
                "since": plan.since,
                "until": plan.until,
                "limit": plan.page_limit,
            },
        )
    persister = BatchCapturePersister(repository, query_ids, raw_dir)
    try:
        summary = collect(
            plan,
            client.keyword_search,
            checkpoint_path=checkpoint_path,
            resume=resume,
            capture_hook=persister,
        )
    except Exception:
        repository.complete_collection_batch(batch_id, failed=True)
        raise
    failed = summary["stop_reason"] in {"HTTP_ERROR", "INVALID_RESPONSE"}
    repository.complete_collection_batch(batch_id, failed=failed)
    result: Dict[str, object] = dict(summary)
    result["batch_id"] = batch_id
    result["batch_key"] = batch_key
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", action="append", dest="queries")
    parser.add_argument(
        "--search-type", action="append", choices=("TOP", "RECENT"), dest="search_types"
    )
    parser.add_argument("--page-limit", type=int, default=5)
    parser.add_argument("--target-unique", type=int, default=100)
    parser.add_argument("--hard-cap", type=int, default=200)
    parser.add_argument("--max-requests", type=int, default=3)
    parser.add_argument("--interval", type=float, default=2.0)
    parser.add_argument("--since", default="")
    parser.add_argument("--until", default="")
    parser.add_argument("--database", type=Path, default=Path("data/social_content.sqlite3"))
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw"))
    parser.add_argument("--checkpoint", type=Path, default=Path("data/checkpoints/m2.json"))
    parser.add_argument("--report", type=Path, default=Path("data/reports/m2-collection.json"))
    parser.add_argument("--resume", action="store_true")
    return parser


def main(argv: Sequence[str] = ()) -> int:
    args = build_parser().parse_args(argv or None)
    token = os.environ.get("THREADS_ACCESS_TOKEN", "")
    if not token:
        print("HG-01: set THREADS_ACCESS_TOKEN before live collection", file=sys.stderr)
        return 2
    plan = CollectionPlan(
        queries=tuple(args.queries or DEFAULT_QUERIES),
        search_types=tuple(args.search_types or ("RECENT", "TOP")),
        fields=DEFAULT_FIELDS,
        page_limit=args.page_limit,
        target_unique=args.target_unique,
        hard_cap=args.hard_cap,
        max_requests=args.max_requests,
        live_interval_seconds=args.interval,
        since=args.since,
        until=args.until,
    )
    args.database.parent.mkdir(parents=True, exist_ok=True)
    batch_key = "m2-" + _utc_now_compact()
    with Repository(args.database) as repository:
        result = run_collection_batch(
            repository,
            ThreadsClient(token),
            plan,
            batch_key=batch_key,
            raw_dir=args.raw_dir,
            checkpoint_path=args.checkpoint,
            resume=args.resume,
        )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(summary_json(result), encoding="utf-8")
    print(
        "Stored batch {batch_key}: unique={unique_count} observations={observation_count} "
        "stop={stop_reason}; report={report}".format(report=args.report, **result)
    )
    return 1 if result["stop_reason"] in {"HTTP_ERROR", "INVALID_RESPONSE"} else 0


if __name__ == "__main__":
    raise SystemExit(main())
