"""Canonical, closed browser-observation normalization for M3."""

import hashlib
import json
from typing import Any, Dict, Optional
from urllib.parse import urlsplit

BROWSER_OBSERVATION_CONTRACT_VERSION = "M3_BROWSER_OBSERVATION_V1"
BROWSER_NORMALIZER_VERSION = "m3-browser-normalizer-v1"

OBSERVABLE_FIELDS = {
    "source_post_id",
    "author_name",
    "username",
    "text",
    "timestamp",
    "public_counters.view_count",
    "public_counters.like_count",
    "public_counters.reply_count",
    "public_counters.repost_count",
    "public_counters.quote_count",
    "public_counters.share_count",
    "media_type",
    "has_image",
    "has_video",
}

_FORBIDDEN_KEYS = {
    "html",
    "dom",
    "raw_dom",
    "outer_html",
    "inner_html",
    "cookie",
    "cookies",
    "authorization",
    "access_token",
    "token",
    "password",
    "headers",
}


def canonical_threads_post_url(value: str) -> str:
    """Return the stable Threads post URL identity without query or fragment."""
    if not isinstance(value, str):
        raise ValueError("post_url must be a string")
    parsed = urlsplit(value)
    if parsed.scheme.lower() != "https" or (parsed.hostname or "").lower() not in {
        "threads.net",
        "www.threads.net",
    }:
        raise ValueError("post_url must be an HTTPS Threads URL")
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) != 3 or not parts[0].startswith("@") or parts[1] != "post":
        raise ValueError("post_url must identify one Threads post")
    username = parts[0][1:].lower()
    post_code = parts[2]
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
    if not username or any(character not in allowed for character in username):
        raise ValueError("post_url username is invalid")
    if not post_code or any(character not in allowed for character in post_code):
        raise ValueError("post_url post code is invalid")
    return "https://www.threads.net/@" + username + "/post/" + post_code


def _canonical_json(value: Dict[str, Any]) -> str:
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True
    )


def browser_observation_payload_sha256(observation: Dict[str, Any]) -> str:
    """Hash the closed capture envelope, excluding the self-referential hash field."""
    payload = {key: value for key, value in observation.items() if key != "payload_sha256"}
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def browser_normalized_payload(observation: Dict[str, Any]) -> Dict[str, Any]:
    """Derive only stable observed post fields; context and capture time remain provenance."""
    return {
        "schema_version": 1,
        "source": "threads",
        "post_url": canonical_threads_post_url(str(observation["post_url"])),
        "source_post_id": observation.get("source_post_id"),
        "author_name": observation.get("author_name"),
        "username": observation.get("username"),
        "text": observation.get("text"),
        "timestamp": observation.get("timestamp"),
        "public_counters": dict(observation.get("public_counters", {})),
        "approximate_views": (
            dict(observation["approximate_views"])
            if isinstance(observation.get("approximate_views"), dict)
            else None
        ),
        "media_type": observation.get("media_type"),
        "has_image": observation.get("has_image"),
        "has_video": observation.get("has_video"),
    }


def canonical_browser_normalized_payload(observation: Dict[str, Any]) -> str:
    return _canonical_json(browser_normalized_payload(observation))


def _reject_forbidden(value: Any) -> None:
    if isinstance(value, dict):
        if _FORBIDDEN_KEYS.intersection(key.lower() for key in value):
            raise ValueError("browser observation contains forbidden browser or credential data")
        for child in value.values():
            _reject_forbidden(child)
    elif isinstance(value, list):
        for child in value:
            _reject_forbidden(child)


def _observed_value(observation: Dict[str, Any], field: str) -> Any:
    if field.startswith("public_counters."):
        counters = observation.get("public_counters")
        return counters.get(field.split(".", 1)[1]) if isinstance(counters, dict) else None
    return observation.get(field)


def approximate_view_band(value: int) -> str:
    if value < 1_000:
        return "LT_1K"
    if value < 10_000:
        return "1K_10K"
    if value < 100_000:
        return "10K_100K"
    if value < 1_000_000:
        return "100K_1M"
    return "1M_PLUS"


def validate_browser_observation(observation: Dict[str, Any]) -> str:
    """Enforce semantic rules beyond JSON Schema and return the canonical post URL."""
    _reject_forbidden(observation)
    required_keys = {
        "schema_version",
        "observation_type",
        "source",
        "post_url",
        "source_post_id",
        "author_name",
        "username",
        "text",
        "timestamp",
        "public_counters",
        "media_type",
        "has_image",
        "has_video",
        "collection_context",
        "observed_fields",
        "collected_at",
        "extractor_version",
        "payload_sha256",
    }
    optional_keys = {"metric_observation_statuses", "approximate_views"}
    if not required_keys.issubset(observation) or not set(observation).issubset(
        required_keys | optional_keys
    ):
        raise ValueError("browser observation does not match the closed contract")
    if observation.get("schema_version") != 1 or observation.get("source") != "threads":
        raise ValueError("browser observation version or source is invalid")
    observation_type = observation.get("observation_type")
    if observation_type not in {"SEARCH_CARD", "POST_DETAIL"}:
        raise ValueError("browser observation type is invalid")
    nullable_strings = (
        "source_post_id",
        "author_name",
        "username",
        "text",
        "timestamp",
        "media_type",
    )
    if any(
        observation.get(key) is not None
        and not isinstance(observation.get(key), str)
        for key in nullable_strings
    ):
        raise ValueError("browser observation text fields must be strings or null")
    if any(
        observation.get(key) is not None
        and not isinstance(observation.get(key), bool)
        for key in ("has_image", "has_video")
    ):
        raise ValueError("browser observation media flags must be booleans or null")
    counters = observation.get("public_counters")
    counter_names = {
        "view_count",
        "like_count",
        "reply_count",
        "repost_count",
        "quote_count",
        "share_count",
    }
    if not isinstance(counters, dict) or not set(counters).issubset(counter_names):
        raise ValueError("public counters do not match the closed contract")
    if any(
        value is not None
        and (isinstance(value, bool) or not isinstance(value, int) or value < 0)
        for value in counters.values()
    ):
        raise ValueError("public counters must be nonnegative integers or null")
    metric_statuses = observation.get("metric_observation_statuses")
    if metric_statuses is not None:
        allowed_statuses = {
            "OBSERVED",
            "NOT_PRESENT",
            "NOT_OBSERVED",
            "EXTRACTION_FAILED",
        }
        if (
            observation_type != "POST_DETAIL"
            or not isinstance(metric_statuses, dict)
            or set(metric_statuses) != counter_names
            or any(value not in allowed_statuses for value in metric_statuses.values())
        ):
            raise ValueError("metric observation statuses do not match the contract")
        for name, value in counters.items():
            status_value = metric_statuses[name]
            if (value is not None) != (status_value == "OBSERVED"):
                raise ValueError("metric value and observation status disagree")
    approximate_views = observation.get("approximate_views")
    if approximate_views is not None:
        expected_approximate_keys = {
            "display",
            "normalized_approx",
            "precision",
            "source",
            "view_band",
            "observed_at",
            "extractor_version",
            "normalizer_version",
        }
        if observation_type != "POST_DETAIL" or not isinstance(approximate_views, dict):
            raise ValueError("approximate Views require a POST_DETAIL observation")
        if set(approximate_views) != expected_approximate_keys:
            raise ValueError("approximate Views do not match the closed contract")
        display = approximate_views["display"]
        normalized_approx = approximate_views["normalized_approx"]
        if not isinstance(display, str) or not display or len(display) > 32:
            raise ValueError("approximate Views display is invalid")
        if (
            isinstance(normalized_approx, bool)
            or not isinstance(normalized_approx, int)
            or normalized_approx < 0
        ):
            raise ValueError("approximate Views normalized value is invalid")
        if approximate_views["precision"] != "ROUNDED":
            raise ValueError("approximate Views precision is invalid")
        if approximate_views["source"] != "POST_DETAIL_PAGE":
            raise ValueError("approximate Views source is invalid")
        if approximate_views["view_band"] not in {
            "LT_1K", "1K_10K", "10K_100K", "100K_1M", "1M_PLUS"
        }:
            raise ValueError("approximate Views band is invalid")
        if approximate_views["view_band"] != approximate_view_band(normalized_approx):
            raise ValueError("approximate Views band disagrees with normalized value")
        if approximate_views["extractor_version"] != observation.get("extractor_version"):
            raise ValueError("approximate Views extractor provenance is invalid")
        if not all(
            isinstance(approximate_views[key], str) and approximate_views[key]
            for key in ("observed_at", "normalizer_version")
        ):
            raise ValueError("approximate Views provenance is invalid")
    canonical_url = canonical_threads_post_url(str(observation.get("post_url", "")))
    if observation.get("post_url") != canonical_url:
        raise ValueError("post_url must already be canonical")
    expected_hash = browser_observation_payload_sha256(observation)
    if observation.get("payload_sha256") != expected_hash:
        raise ValueError("browser observation payload hash mismatch")
    fields = observation.get("observed_fields")
    if not isinstance(fields, list):
        raise ValueError("observed_fields must be a list")
    names = []
    for item in fields:
        if not isinstance(item, dict) or set(item) != {
            "field",
            "value",
            "surface",
            "observed_at",
            "extractor_version",
        }:
            raise ValueError("observed field provenance does not match the closed contract")
        field = item["field"]
        if field not in OBSERVABLE_FIELDS or field in names:
            raise ValueError("observed field is unknown or duplicated")
        value = _observed_value(observation, str(field))
        if value is None or item["value"] != value:
            raise ValueError("observed field provenance does not match the payload")
        names.append(field)
    expected_surface = (
        "threads_search_card" if observation_type == "SEARCH_CARD" else "threads_post_detail"
    )
    context = observation.get("collection_context")
    if (
        not isinstance(context, dict)
        or not set(context).issubset({"surface", "page_url", "query", "position"})
        or context.get("surface") != expected_surface
    ):
        raise ValueError("collection context does not match observation type")
    position = context.get("position")
    if position is not None and (
        isinstance(position, bool) or not isinstance(position, int) or position < 0
    ):
        raise ValueError("collection context position must be a nonnegative integer or null")
    if any(
        context.get(key) is not None and not isinstance(context.get(key), str)
        for key in ("page_url", "query")
    ):
        raise ValueError("collection context text fields must be strings or null")
    if any(item["surface"] != expected_surface for item in fields):
        raise ValueError("observed field surface does not match observation type")
    extractor = observation.get("extractor_version")
    if not isinstance(extractor, str) or not extractor or any(
        item["extractor_version"] != extractor for item in fields
    ):
        raise ValueError("observed field extractor does not match observation extractor")
    return canonical_url


def browser_observation_status(observation: Dict[str, Any]) -> str:
    if observation["observation_type"] == "POST_DETAIL":
        return "DETAIL_ENRICHED"
    counters = observation.get("public_counters")
    view_count: Optional[Any] = counters.get("view_count") if isinstance(counters, dict) else None
    return "DETAIL_PENDING" if view_count is None else "COLLECTED"
