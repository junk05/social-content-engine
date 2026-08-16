"""Closed provenance contract for explicit browser detail attempts."""

from datetime import datetime
from typing import Any

DETAIL_ATTEMPT_CONTRACT_VERSION = "M3_BROWSER_DETAIL_ATTEMPT_V1"

DETAIL_FAILURE_TYPES = {
    "NAVIGATION_FAILED",
    "PAGE_UNAVAILABLE",
    "EXTRACTION_FAILED",
    "VALIDATION_FAILED",
    "TIMEOUT",
}

DETAIL_FAILURE_REASONS = {
    "NETWORK_ERROR",
    "POST_NOT_FOUND",
    "LOGIN_REQUIRED",
    "EXPECTED_FIELD_MISSING",
    "UNRECOGNIZED_PAGE",
    "INVALID_OBSERVATION",
    "TIME_LIMIT_EXCEEDED",
}


def validate_detail_attempt_provenance(
    *, attempted_at: Any, extractor_version: Any, contract_version: Any
) -> None:
    """Validate the small, non-secret provenance shared by every detail attempt."""
    if contract_version != DETAIL_ATTEMPT_CONTRACT_VERSION:
        raise ValueError("detail attempt contract version is invalid")
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:-"
    if not (
        isinstance(extractor_version, str)
        and 0 < len(extractor_version) <= 128
        and all(character in allowed for character in extractor_version)
    ):
        raise ValueError("detail attempt extractor version is invalid")
    if not isinstance(attempted_at, str):
        raise ValueError("detail attempt time must be an RFC3339 timestamp")
    try:
        parsed = datetime.fromisoformat(attempted_at.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("detail attempt time must be an RFC3339 timestamp") from error
    if parsed.tzinfo is None:
        raise ValueError("detail attempt time must include a timezone")


def validate_detail_failure(failure_type: Any, failure_reason: Any) -> None:
    """Reject free-form or secret-bearing failure detail at the data boundary."""
    if failure_type not in DETAIL_FAILURE_TYPES:
        raise ValueError("detail failure type is invalid")
    if failure_reason not in DETAIL_FAILURE_REASONS:
        raise ValueError("detail failure reason is invalid")
