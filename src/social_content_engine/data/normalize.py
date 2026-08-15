"""Deterministic Threads post normalization without inferred fields."""

from datetime import datetime, timezone
from typing import Any, Dict, Optional


def _string_or_none(value: Any) -> Optional[str]:
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        return str(value)
    return None


def normalize_threads_post(
    post: Dict[str, Any], raw_sha256: str, normalized_at: Optional[str] = None
) -> Dict[str, Any]:
    """Map only fields present in the official response; never infer values."""
    source_post_id = _string_or_none(post.get("id"))
    if not source_post_id:
        raise ValueError("Threads post is missing a non-empty id")

    owner = post.get("owner")
    if isinstance(owner, dict):
        author_id = _string_or_none(owner.get("id"))
    else:
        author_id = _string_or_none(owner)

    return {
        "schema_version": 1,
        "source": "threads",
        "source_post_id": source_post_id,
        "author_id": author_id,
        "username": _string_or_none(post.get("username")),
        "text": _string_or_none(post.get("text")),
        "permalink": _string_or_none(post.get("permalink")),
        "published_at": _string_or_none(post.get("timestamp")),
        "media_type": _string_or_none(post.get("media_type")),
        "raw_sha256": raw_sha256,
        "normalized_at": normalized_at
        or datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }
