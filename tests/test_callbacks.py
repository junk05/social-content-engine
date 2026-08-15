import base64
import hashlib
import hmac
import json
import unittest
import urllib.parse
from pathlib import Path
from typing import Any, Dict

from social_content_engine.callbacks.service import CallbackConfig, MetaCallbackService
from social_content_engine.callbacks.signed_request import SignedRequestError, parse_signed_request

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "meta_callbacks" / "cases.json"
FIXTURES = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
FIXTURE_SIGNING_KEY = "fixture-signing-key"


def encode_base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def make_signed_request(payload: Dict[str, Any], secret: str = FIXTURE_SIGNING_KEY) -> str:
    encoded_payload = encode_base64url(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    signature = hmac.new(
        secret.encode("utf-8"), encoded_payload.encode("ascii"), hashlib.sha256
    ).digest()
    return encode_base64url(signature) + "." + encoded_payload


class CallbackTest(unittest.TestCase):
    def setUp(self) -> None:
        self.service = MetaCallbackService(
            CallbackConfig(
                app_secret=FIXTURE_SIGNING_KEY,
                oauth_state="fixture-state",
                public_base_url="https://fixture-tunnel.example",
            )
        )

    def test_oauth_success_fixture(self) -> None:
        case = FIXTURES["oauth_success"]
        response = self.service.handle_get(case["path"], case["query"])
        self.assertEqual(case["expected_status"], response.status)
        self.assertEqual(case["expected_body"], json.loads(response.body))
        self.assertNotIn(b"fixture-authorization-code", response.body)

    def test_oauth_denied_fixture(self) -> None:
        case = FIXTURES["oauth_denied"]
        response = self.service.handle_get(case["path"], case["query"])
        self.assertEqual(case["expected_status"], response.status)
        self.assertEqual(case["expected_body"], json.loads(response.body))

    def test_oauth_rejects_missing_or_wrong_state(self) -> None:
        for query in ({"code": "code"}, {"code": "code", "state": "wrong"}):
            with self.subTest(query=query):
                response = self.service.handle_get("/meta/oauth/callback", query)
                self.assertEqual(400, response.status)
                self.assertEqual("invalid_state", json.loads(response.body)["error"])

    def test_deauthorization_fixture(self) -> None:
        case = FIXTURES["deauthorization"]
        response = self._signed_post(case["path"], case["payload"])
        self.assertEqual(case["expected_status"], response.status)
        self.assertEqual(case["expected_body"], json.loads(response.body))

    def test_data_deletion_fixture_and_status(self) -> None:
        case = FIXTURES["data_deletion"]
        response = self._signed_post(case["path"], case["payload"])
        self.assertEqual(case["expected_status"], response.status)
        body = json.loads(response.body)
        self.assertRegex(body["confirmation_code"], r"^[a-f0-9]{32}$")
        self.assertEqual(
            "https://fixture-tunnel.example/meta/data-deletion/status?code="
            + body["confirmation_code"],
            body["url"],
        )
        status = self.service.handle_get(
            "/meta/data-deletion/status", {"code": body["confirmation_code"]}
        )
        self.assertEqual(
            {"confirmation_code": body["confirmation_code"], "status": "completed"},
            json.loads(status.body),
        )

    def test_signed_callbacks_reject_missing_invalid_and_wrong_algorithm(self) -> None:
        missing = self.service.handle_post(
            "/meta/deauthorization", b"other=value", "application/x-www-form-urlencoded"
        )
        self.assertEqual(400, missing.status)

        invalid_body = urllib.parse.urlencode({"signed_request": "invalid.value"}).encode()
        invalid = self.service.handle_post(
            "/meta/deauthorization", invalid_body, "application/x-www-form-urlencoded"
        )
        self.assertEqual(400, invalid.status)

        signed = make_signed_request({"algorithm": "none", "user_id": "fixture-user"})
        with self.assertRaises(SignedRequestError):
            parse_signed_request(signed, FIXTURE_SIGNING_KEY)

    def test_signature_tampering_is_rejected(self) -> None:
        signed = make_signed_request({"algorithm": "HMAC-SHA256", "user_id": "fixture-user"})
        tampered = signed[:-1] + ("A" if signed[-1] != "A" else "B")
        with self.assertRaises(SignedRequestError):
            parse_signed_request(tampered, FIXTURE_SIGNING_KEY)

    def test_requires_https_public_base_url(self) -> None:
        with self.assertRaises(ValueError):
            MetaCallbackService(
                CallbackConfig(
                    app_secret=FIXTURE_SIGNING_KEY,
                    oauth_state="fixture-state",
                    public_base_url="http://localhost:8787",
                )
            )

    def _signed_post(self, path: str, payload: Dict[str, Any]):
        signed_request = make_signed_request(payload)
        body = urllib.parse.urlencode({"signed_request": signed_request}).encode("utf-8")
        return self.service.handle_post(path, body, "application/x-www-form-urlencoded")


if __name__ == "__main__":
    unittest.main()
