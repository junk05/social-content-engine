"""Validation for Meta signed_request payloads."""

import base64
import hashlib
import hmac
import json
from typing import Any, Dict


class SignedRequestError(ValueError):
    """Raised when a signed_request is malformed or untrusted."""


def _decode_base64url(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    try:
        return base64.urlsafe_b64decode((value + padding).encode("ascii"))
    except (ValueError, UnicodeEncodeError) as error:
        raise SignedRequestError("invalid base64url encoding") from error


def parse_signed_request(signed_request: str, app_secret: str) -> Dict[str, Any]:
    """Verify HMAC-SHA256 before returning a decoded Meta payload."""
    if not app_secret:
        raise SignedRequestError("app secret is not configured")
    try:
        encoded_signature, encoded_payload = signed_request.split(".", 1)
    except ValueError as error:
        raise SignedRequestError("signed_request must contain two segments") from error

    signature = _decode_base64url(encoded_signature)
    expected = hmac.new(
        app_secret.encode("utf-8"), encoded_payload.encode("ascii"), hashlib.sha256
    ).digest()
    if not hmac.compare_digest(signature, expected):
        raise SignedRequestError("invalid signed_request signature")

    try:
        payload = json.loads(_decode_base64url(encoded_payload).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SignedRequestError("signed_request payload is not valid JSON") from error
    if not isinstance(payload, dict):
        raise SignedRequestError("signed_request payload must be an object")
    if str(payload.get("algorithm", "")).upper() != "HMAC-SHA256":
        raise SignedRequestError("unsupported signed_request algorithm")
    user_id = payload.get("user_id")
    if not isinstance(user_id, (str, int)) or not str(user_id):
        raise SignedRequestError("signed_request payload is missing user_id")
    return payload
