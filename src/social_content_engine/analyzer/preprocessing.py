"""Deterministic, observation-only preprocessing for M1 Analyzer Input."""

import hashlib
import json
import re
import unicodedata
from typing import Any, Dict, Mapping, Optional

URL_PATTERN = re.compile(r"https?://[^\s]+", re.IGNORECASE)
HASHTAG_PATTERN = re.compile(r"(?<!\w)#[\w]+", re.UNICODE)
MENTION_PATTERN = re.compile(r"(?<!\w)@[\w.]+", re.UNICODE)


def _optional_string(value: Any) -> Optional[str]:
    return value if isinstance(value, str) else None


def _emoji_count(text: str) -> int:
    """Count emoji-like Unicode code points without guessing semantic meaning."""
    return sum(
        1
        for character in text
        if 0x1F000 <= ord(character) <= 0x1FAFF
        or 0x2600 <= ord(character) <= 0x27BF
    )


def build_analyzer_input(post: Mapping[str, Any]) -> Dict[str, Any]:
    """Build the immutable logical Analyzer Input from normalized observations."""
    source = post.get("source")
    source_post_id = post.get("source_post_id")
    if not isinstance(source, str) or not source:
        raise ValueError("normalized post is missing source")
    if not isinstance(source_post_id, str) or not source_post_id:
        raise ValueError("normalized post is missing source_post_id")

    text = unicodedata.normalize("NFC", _optional_string(post.get("text")) or "")
    return {
        "schema_version": 1,
        "source": source,
        "source_post_id": source_post_id,
        "text": text,
        "created_at": _optional_string(post.get("published_at")),
        "permalink": _optional_string(post.get("permalink")),
        "author_id": _optional_string(post.get("author_id")),
        "public_metrics": post.get("public_metrics")
        if isinstance(post.get("public_metrics"), dict)
        else {},
        "reply_to_post_id": _optional_string(post.get("reply_to_post_id")),
        "root_post_id": _optional_string(post.get("root_post_id")),
        "language_hint": _optional_string(post.get("language_hint")),
        "text_features": {
            "character_count": len(text),
            "line_count": len(text.splitlines()) if text else 0,
            "url_count": len(URL_PATTERN.findall(text)),
            "hashtag_count": len(HASHTAG_PATTERN.findall(text)),
            "mention_count": len(MENTION_PATTERN.findall(text)),
            "emoji_count": _emoji_count(text),
            "question_mark_count": text.count("?") + text.count("？"),
            "exclamation_mark_count": text.count("!") + text.count("！"),
        },
    }


def canonical_json_bytes(document: Mapping[str, Any]) -> bytes:
    """Serialize a JSON-compatible mapping deterministically as UTF-8 bytes."""
    return json.dumps(
        document, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")


def input_sha256(document: Mapping[str, Any]) -> str:
    """Hash the canonical Analyzer Input serialization."""
    return hashlib.sha256(canonical_json_bytes(document)).hexdigest()
