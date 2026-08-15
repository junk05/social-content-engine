"""Low-volume Post Insights evidence spike.

Official specification: https://www.postman.com/meta/threads/request/ndeeu6p/get-post-insights
Whether insights are available for another account's public post remains UNKNOWN.
"""

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from social_content_engine import __version__
from social_content_engine.data.repository import Repository

from .client import POST_INSIGHT_METRICS, HttpCapture, ThreadsClient


def run_insights_spike(
    *,
    repository: Repository,
    fetch: Any,
    thread_id: str,
    raw_dir: Path,
    metrics: Sequence[str] = POST_INSIGHT_METRICS,
    collector_version: str = __version__,
) -> Dict[str, Any]:
    """Capture the exact HTTP body first, then store only explicit metric values."""
    requested = tuple(metrics)
    capture: HttpCapture = fetch(thread_id=thread_id, metrics=",".join(requested))
    digest = hashlib.sha256(capture.body).hexdigest()
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_path = raw_dir / (digest + ".json")
    raw_path.write_bytes(capture.body)
    run_id = repository.add_collection_run(
        endpoint=capture.endpoint,
        request={"params": capture.request_params},
        started_at=capture.started_at,
        completed_at=capture.completed_at,
        http_status=capture.status,
        response_headers=capture.headers,
        raw_response=capture.body,
        raw_response_sha256=digest,
        collector_version=collector_version,
    )
    stored: List[str] = []
    if 200 <= capture.status < 300:
        payload = json.loads(capture.body.decode("utf-8"))
        for name, value in _explicit_metric_values(payload, requested).items():
            repository.add_metric_observation(
                source="threads",
                source_post_id=thread_id,
                metric_name=name,
                metric_value=value,
                observed_at=capture.completed_at,
                collection_run_id=run_id,
                api_field=name,
                unit="count",
                collector_version=collector_version,
            )
            stored.append(name)
    return {
        "collection_run_id": run_id,
        "http_status": capture.status,
        "raw_sha256": digest,
        "raw_path": str(raw_path),
        "stored_metrics": sorted(stored),
        "unknown_metrics": sorted(set(requested) - set(stored)),
    }


def _explicit_metric_values(payload: Any, requested: Sequence[str]) -> Dict[str, int]:
    if not isinstance(payload, Mapping) or not isinstance(payload.get("data"), list):
        raise ValueError("Post Insights response data must be a list")
    allowed = set(requested)
    result: Dict[str, int] = {}
    for item in payload["data"]:
        if not isinstance(item, Mapping):
            raise ValueError("Post Insights data items must be objects")
        name = item.get("name")
        if name not in allowed:
            continue
        value: Optional[Any] = None
        total = item.get("total_value")
        values = item.get("values")
        if isinstance(total, Mapping) and "value" in total:
            value = total["value"]
        elif isinstance(values, list) and len(values) == 1 and isinstance(values[0], Mapping):
            value = values[0].get("value")
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            continue
        result[str(name)] = value
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--thread-id", required=True)
    parser.add_argument("--database", type=Path, default=Path("data/social_content.sqlite3"))
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw/insights"))
    return parser


def main(argv: Sequence[str] = ()) -> int:
    args = build_parser().parse_args(argv or None)
    token = os.environ.get("THREADS_ACCESS_TOKEN", "")
    if not token:
        print(
            "HG-01: set THREADS_ACCESS_TOKEN before running the live insights spike",
            file=sys.stderr,
        )
        return 2
    args.database.parent.mkdir(parents=True, exist_ok=True)
    with Repository(args.database) as repository:
        result = run_insights_spike(
            repository=repository,
            fetch=ThreadsClient(token, max_retries=0).post_insights,
            thread_id=args.thread_id,
            raw_dir=args.raw_dir,
        )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if 200 <= int(result["http_status"]) < 300 else 1


if __name__ == "__main__":
    raise SystemExit(main())
