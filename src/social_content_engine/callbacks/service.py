"""Framework-free request/response behavior for Meta callbacks."""

import hashlib
import hmac
import json
import re
import urllib.parse
from dataclasses import dataclass
from typing import Mapping

from .signed_request import SignedRequestError, parse_signed_request

CODE_PATTERN = re.compile(r"^[A-Za-z0-9_-]{16,128}$")


@dataclass(frozen=True)
class CallbackConfig:
    app_secret: str
    oauth_state: str
    public_base_url: str

    def validate(self) -> None:
        if not self.app_secret:
            raise ValueError("THREADS_APP_SECRET is required")
        if not self.oauth_state:
            raise ValueError("META_OAUTH_STATE is required")
        parsed = urllib.parse.urlparse(self.public_base_url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("META_PUBLIC_BASE_URL must be an HTTPS origin")


@dataclass(frozen=True)
class CallbackResponse:
    status: int
    body: bytes
    content_type: str = "application/json; charset=utf-8"

    @classmethod
    def json(cls, status: int, payload: Mapping[str, object]) -> "CallbackResponse":
        return cls(
            status=status,
            body=json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
        )


class MetaCallbackService:
    def __init__(self, config: CallbackConfig) -> None:
        config.validate()
        self.config = config

    def handle_get(self, path: str, query: Mapping[str, str]) -> CallbackResponse:
        if path == "/meta/oauth/callback":
            return self._oauth_callback(query)
        if path == "/meta/data-deletion/status":
            return self._deletion_status(query)
        return CallbackResponse.json(404, {"error": "not_found"})

    def handle_post(self, path: str, body: bytes, content_type: str) -> CallbackResponse:
        if content_type.split(";", 1)[0].strip().lower() != "application/x-www-form-urlencoded":
            return CallbackResponse.json(415, {"error": "unsupported_media_type"})
        try:
            form = urllib.parse.parse_qs(body.decode("utf-8"), strict_parsing=True)
        except (UnicodeDecodeError, ValueError):
            return CallbackResponse.json(400, {"error": "invalid_form"})
        signed_values = form.get("signed_request", [])
        if len(signed_values) != 1:
            return CallbackResponse.json(400, {"error": "missing_signed_request"})
        try:
            payload = parse_signed_request(signed_values[0], self.config.app_secret)
        except SignedRequestError:
            return CallbackResponse.json(400, {"error": "invalid_signed_request"})

        if path == "/meta/deauthorization":
            return CallbackResponse.json(200, {"status": "accepted"})
        if path == "/meta/data-deletion":
            user_id = str(payload["user_id"])
            confirmation_code = self._confirmation_code(user_id)
            status_url = (
                self.config.public_base_url.rstrip("/")
                + "/meta/data-deletion/status?code="
                + urllib.parse.quote(confirmation_code)
            )
            return CallbackResponse.json(
                200, {"url": status_url, "confirmation_code": confirmation_code}
            )
        return CallbackResponse.json(404, {"error": "not_found"})

    def _oauth_callback(self, query: Mapping[str, str]) -> CallbackResponse:
        state = query.get("state", "")
        if not hmac.compare_digest(state, self.config.oauth_state):
            return CallbackResponse.json(400, {"error": "invalid_state"})
        if query.get("error"):
            return CallbackResponse.json(
                400,
                {
                    "status": "authorization_denied",
                    "error": query["error"],
                    "error_reason": query.get("error_reason", ""),
                    "error_description": query.get("error_description", ""),
                },
            )
        code = query.get("code", "")
        if not code:
            return CallbackResponse.json(400, {"error": "missing_code"})
        return CallbackResponse.json(
            200,
            {
                "status": "authorization_code_received",
                "message": (
                    "Exchange the code from the browser URL; it is not stored by this server."
                ),
            },
        )

    def _deletion_status(self, query: Mapping[str, str]) -> CallbackResponse:
        code = query.get("code", "")
        if not CODE_PATTERN.fullmatch(code):
            return CallbackResponse.json(400, {"error": "invalid_confirmation_code"})
        return CallbackResponse.json(200, {"confirmation_code": code, "status": "completed"})

    def _confirmation_code(self, user_id: str) -> str:
        return hmac.new(
            self.config.app_secret.encode("utf-8"),
            ("data-deletion:" + user_id).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()[:32]
