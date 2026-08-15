"""Ingest an exact Threads response into raw and normalized storage."""

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, List

from .normalize import normalize_threads_post
from .repository import Repository


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def ingest_response(
    repository: Repository,
    *,
    endpoint: str,
    request: Dict[str, Any],
    started_at: str,
    completed_at: str,
    http_status: int,
    response_headers: Dict[str, str],
    raw_response: bytes,
    collector_version: str,
) -> List[Dict[str, Any]]:
    """Persist the full raw body before deriving individual post records."""
    response_sha = hashlib.sha256(raw_response).hexdigest()
    run_id = repository.add_collection_run(
        endpoint=endpoint,
        request=request,
        started_at=started_at,
        completed_at=completed_at,
        http_status=http_status,
        response_headers=response_headers,
        raw_response=raw_response,
        raw_response_sha256=response_sha,
        collector_version=collector_version,
    )
    payload = json.loads(raw_response.decode("utf-8"))
    items = payload.get("data", [])
    if not isinstance(items, list):
        raise ValueError("Threads response data must be a list")

    normalized: List[Dict[str, Any]] = []
    retrieved_at = completed_at or _now()
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("Threads response item must be an object")
        raw_item = json.dumps(
            item, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
        raw_sha = hashlib.sha256(raw_item).hexdigest()
        normalized_item = normalize_threads_post(item, raw_sha, normalized_at=retrieved_at)
        raw_post_id = repository.add_raw_post(
            collection_run_id=run_id,
            source_post_id=normalized_item["source_post_id"],
            raw_json=raw_item,
            raw_sha256=raw_sha,
            retrieved_at=retrieved_at,
        )
        repository.upsert_normalized_post(normalized_item, source_raw_post_id=raw_post_id)
        normalized.append(normalized_item)
    return normalized
