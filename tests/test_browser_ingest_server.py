import copy
import http.client
import json
import tempfile
import threading
import unittest
from http.server import HTTPServer
from pathlib import Path

from social_content_engine.browser_ingest.server import (
    DETAIL_FAILURE_PATH,
    INGEST_PATH,
    MAX_BODY_BYTES,
    PENDING_DETAILS_PATH,
    THREAD_SEQUENCE_PATH,
    BrowserIngestService,
    configured_handler,
    load_schema,
    parse_extension_origins,
    require_loopback_host,
)
from social_content_engine.data.browser_observation import browser_observation_payload_sha256
from social_content_engine.data.repository import Repository
from tests.test_browser_observation_repository import observation

ALLOWED_ORIGIN = "chrome-extension://abcdefghijklmnopabcdefghijklmnop"


class BrowserIngestServerTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.repository = Repository(Path(temporary.name) / "browser.sqlite3")
        self.addCleanup(self.repository.close)
        self.service = BrowserIngestService(
            self.repository, {ALLOWED_ORIGIN}, load_schema()
        )

    def post(self, payload: dict, **kwargs: str):
        return self.service.handle_post(
            "/browser-ingest/threads",
            kwargs.get("origin", ALLOWED_ORIGIN),
            kwargs.get("content_type", "application/json"),
            json.dumps(payload).encode("utf-8"),
        )

    def observed_url(self, post_code: str, **kwargs: object) -> dict:
        payload = observation(**kwargs)
        payload["post_url"] = (
            "https://www.threads.net/@fixture/post/" + post_code
        )
        payload["payload_sha256"] = browser_observation_payload_sha256(payload)
        return payload

    def test_options_success_and_duplicate_observation(self) -> None:
        preflight = self.service.handle_options(
            "/browser-ingest/threads", ALLOWED_ORIGIN
        )
        self.assertEqual(204, preflight.status)
        first = self.post(observation())
        second = self.post(observation())
        self.assertEqual(201, first.status)
        self.assertEqual(201, second.status)
        self.assertNotEqual(first.payload["observation_id"], second.payload["observation_id"])
        self.assertEqual(first.payload["identity_id"], second.payload["identity_id"])
        self.assertEqual(1, second.payload["normalized_version"])
        self.assertEqual(2, self.repository.count("browser_observations"))
        self.assertEqual(1, self.repository.count("browser_post_identities"))

    def test_null_origin_post_requires_exact_extension_identity_header(self) -> None:
        payload = observation()
        accepted = self.service.handle_post(
            INGEST_PATH,
            "null",
            "application/json",
            json.dumps(payload).encode("utf-8"),
            ALLOWED_ORIGIN,
        )
        self.assertEqual(201, accepted.status)
        self.assertEqual(ALLOWED_ORIGIN, accepted.origin)
        rejected = self.service.handle_post(
            INGEST_PATH,
            "null",
            "application/json",
            json.dumps(payload).encode("utf-8"),
            "chrome-extension://pppppppppppppppppppppppppppppppp",
        )
        self.assertEqual(403, rejected.status)

    def test_actual_http_options_and_post_include_allowlisted_cors_headers(self) -> None:
        class StubRepository:
            def add_browser_observation(
                self, payload: dict, *, detail_attempt: dict = None
            ) -> dict:
                return {
                    "browser_observation_id": 1,
                    "browser_post_identity_id": 1,
                    "browser_normalized_version": 1,
                    "status": "DETAIL_PENDING",
                }

        http_service = BrowserIngestService(
            StubRepository(),  # type: ignore[arg-type]
            {ALLOWED_ORIGIN},
            load_schema(),
        )
        server = HTTPServer(
            ("127.0.0.1", 0), configured_handler(http_service)
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        connection = http.client.HTTPConnection(
            "127.0.0.1", server.server_address[1], timeout=2
        )
        try:
            connection.request(
                "OPTIONS",
                "/browser-ingest/threads",
                headers={"Origin": ALLOWED_ORIGIN},
            )
            preflight = connection.getresponse()
            self.assertEqual(204, preflight.status)
            self.assertEqual(
                ALLOWED_ORIGIN, preflight.getheader("Access-Control-Allow-Origin")
            )
            self.assertEqual(
                "GET, POST, OPTIONS",
                preflight.getheader("Access-Control-Allow-Methods"),
            )
            preflight.read()

            body = json.dumps(observation()).encode("utf-8")
            connection.request(
                "POST",
                "/browser-ingest/threads",
                body=body,
                headers={
                    "Origin": ALLOWED_ORIGIN,
                    "Content-Type": "application/json",
                    "Content-Length": str(len(body)),
                },
            )
            accepted = connection.getresponse()
            response_payload = json.loads(accepted.read())
            self.assertEqual(201, accepted.status)
            self.assertEqual(
                ALLOWED_ORIGIN, accepted.getheader("Access-Control-Allow-Origin")
            )
            self.assertEqual("no-store", accepted.getheader("Cache-Control"))
            self.assertEqual("accepted", response_payload["status"])
        finally:
            connection.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_pending_details_are_pending_only_url_only_and_bounded(self) -> None:
        self.post(self.observed_url("PendingA"))
        self.post(self.observed_url("PendingB"))
        self.post(self.observed_url("Collected", view_count=0))
        self.post(
            self.observed_url(
                "Enriched", observation_type="POST_DETAIL", view_count=None
            )
        )
        response = self.service.handle_get(
            PENDING_DETAILS_PATH, "limit=1", ALLOWED_ORIGIN
        )
        self.assertEqual(200, response.status)
        self.assertEqual(1, response.payload["count"])
        self.assertEqual(
            ["https://www.threads.net/@fixture/post/PendingA"],
            response.payload["urls"],
        )
        self.assertEqual({"status", "count", "urls"}, set(response.payload))
        self.assertNotIn("text", response.body.decode("utf-8"))
        self.assertEqual(
            400,
            self.service.handle_get(
                PENDING_DETAILS_PATH, "limit=101", ALLOWED_ORIGIN
            ).status,
        )
        header_authorized = self.service.handle_get(
            PENDING_DETAILS_PATH, "limit=1", "null", ALLOWED_ORIGIN
        )
        self.assertEqual(200, header_authorized.status)
        self.assertEqual(ALLOWED_ORIGIN, header_authorized.origin)
        self.assertEqual(
            403,
            self.service.handle_get(
                PENDING_DETAILS_PATH,
                "limit=1",
                "chrome-extension://pppppppppppppppppppppppppppppppp",
            ).status,
        )

    def test_post_detail_acceptance_records_success_even_when_view_is_missing(self) -> None:
        self.post(self.observed_url("DetailMissingView"))
        accepted = self.post(
            self.observed_url(
                "DetailMissingView", observation_type="POST_DETAIL", view_count=None
            )
        )
        self.assertEqual(201, accepted.status)
        self.assertEqual("DETAIL_ENRICHED", accepted.payload["observation_status"])
        attempt = self.repository.connection.execute(
            """SELECT outcome, detail_observation_id FROM browser_detail_attempts
            ORDER BY id DESC LIMIT 1"""
        ).fetchone()
        self.assertEqual(("SUCCEEDED", accepted.payload["observation_id"]), tuple(attempt))
        self.assertEqual(
            "DETAIL_ENRICHED",
            self.repository.connection.execute(
                """SELECT status FROM browser_post_identities
                WHERE post_url = ?""",
                ("https://www.threads.net/@fixture/post/DetailMissingView",),
            ).fetchone()[0],
        )

    def test_post_detail_observation_and_success_attempt_are_atomic(self) -> None:
        self.repository.connection.execute(
            """CREATE TRIGGER injected_detail_attempt_failure
            BEFORE INSERT ON browser_detail_attempts
            BEGIN SELECT RAISE(ABORT, 'injected'); END"""
        )
        response = self.post(
            self.observed_url("AtomicDetail", observation_type="POST_DETAIL", view_count=9)
        )
        self.assertEqual(500, response.status)
        self.assertEqual({"error": "persistence_failed"}, response.payload)
        self.assertEqual(0, self.repository.count("browser_observations"))
        self.assertEqual(0, self.repository.count("browser_detail_attempts"))

    def test_thread_sequence_requires_matching_detail_and_is_atomic(self) -> None:
        root = self.observed_url("SequenceRoot")
        child = self.observed_url("SequenceChild")
        self.post(root)
        self.post(child)
        detail = self.post(
            self.observed_url("SequenceRoot", observation_type="POST_DETAIL")
        )
        payload = {
            "root_post_url": root["post_url"],
            "detail_observation_id": detail.payload["observation_id"],
            "observed_at": "2026-08-16T04:00:00Z",
            "extractor_version": "fixture-sequence-v1",
            "nodes": [{
                "post_url": root["post_url"],
                "sequence_position": 0,
                "reply_to_post_url": None,
                "same_author_as_root": True,
            }, {
                "post_url": child["post_url"],
                "sequence_position": 1,
                "reply_to_post_url": root["post_url"],
                "same_author_as_root": None,
            }],
        }
        accepted = self.service.handle_post(
            THREAD_SEQUENCE_PATH, ALLOWED_ORIGIN, "application/json",
            json.dumps(payload).encode("utf-8"),
        )
        self.assertEqual(201, accepted.status)
        self.assertEqual({"status": "accepted", "node_count": 2}, accepted.payload)
        self.assertEqual(2, self.repository.count("browser_thread_sequence_observations"))
        bad_detail = dict(payload)
        bad_detail["detail_observation_id"] = 1
        rejected = self.service.handle_post(
            THREAD_SEQUENCE_PATH, ALLOWED_ORIGIN, "application/json",
            json.dumps(bad_detail).encode("utf-8"),
        )
        self.assertEqual(422, rejected.status)
        self.assertEqual(2, self.repository.count("browser_thread_sequence_observations"))
        bad_node = dict(payload)
        bad_node["detail_observation_id"] = detail.payload["observation_id"]
        bad_node["nodes"] = [payload["nodes"][0], {
            "post_url": "https://www.threads.net/@fixture/post/UnknownChild",
            "sequence_position": 1,
            "reply_to_post_url": root["post_url"],
            "same_author_as_root": None,
        }]
        self.assertEqual(422, self.service.handle_post(
            THREAD_SEQUENCE_PATH, ALLOWED_ORIGIN, "application/json",
            json.dumps(bad_node).encode("utf-8"),
        ).status)
        self.assertEqual(2, self.repository.count("browser_thread_sequence_observations"))

    def test_detail_failure_is_closed_and_does_not_affect_other_pending_url(self) -> None:
        first = self.observed_url("FailureA")
        second = self.observed_url("FailureB")
        self.post(first)
        self.post(second)
        failure = {
            "post_url": first["post_url"],
            "attempted_at": "2026-08-16T04:00:00Z",
            "extractor_version": "threads_post_detail_extractor_v1",
            "contract_version": "M3_BROWSER_DETAIL_ATTEMPT_V1",
            "failure_type": "EXTRACTION_FAILED",
            "failure_reason": "EXPECTED_FIELD_MISSING",
        }
        recorded = self.service.handle_post(
            DETAIL_FAILURE_PATH,
            ALLOWED_ORIGIN,
            "application/json",
            json.dumps(failure).encode("utf-8"),
        )
        self.assertEqual(201, recorded.status)
        statuses = dict(
            self.repository.connection.execute(
                "SELECT post_url, status FROM browser_post_identities"
            ).fetchall()
        )
        self.assertEqual("DETAIL_FAILED", statuses[first["post_url"]])
        self.assertEqual("DETAIL_PENDING", statuses[second["post_url"]])
        leaked = dict(failure)
        leaked["cookie"] = "must-not-store"
        rejected = self.service.handle_post(
            DETAIL_FAILURE_PATH,
            ALLOWED_ORIGIN,
            "application/json",
            json.dumps(leaked).encode("utf-8"),
        )
        self.assertEqual(422, rejected.status)
        self.assertNotIn("cookie", rejected.body.decode("utf-8"))
        self.assertEqual(1, self.repository.count("browser_detail_failures"))

    def test_rejects_invalid_schema_hash_origin_content_type_and_oversize(self) -> None:
        invalid_schema = observation()
        invalid_schema["invented"] = "value"
        self.assertEqual(422, self.post(invalid_schema).status)

        invalid_hash = observation()
        invalid_hash["text"] = "changed after hashing"
        self.assertEqual(422, self.post(invalid_hash).status)
        self.assertEqual(
            403,
            self.post(observation(), origin="chrome-extension://pppppppppppppppppppppppppppppppp").status,
        )
        self.assertEqual(
            415, self.post(observation(), content_type="text/plain").status
        )
        oversized = self.service.handle_post(
            "/browser-ingest/threads",
            ALLOWED_ORIGIN,
            "application/json",
            b"x" * (MAX_BODY_BYTES + 1),
        )
        self.assertEqual(413, oversized.status)
        self.assertEqual(0, self.repository.count("browser_observations"))

    def test_credential_like_input_is_rejected_without_secret_echo(self) -> None:
        secret = "secret-browser-token-value"
        payload = copy.deepcopy(observation())
        payload["collection_context"]["access_token"] = secret
        payload["payload_sha256"] = browser_observation_payload_sha256(payload)
        response = self.post(payload)
        self.assertEqual(422, response.status)
        self.assertNotIn(secret, response.body.decode("utf-8"))
        self.assertNotIn("access_token", response.body.decode("utf-8"))
        self.assertEqual({"error": "invalid_observation"}, response.payload)

    def test_loopback_and_extension_origin_configuration_is_closed(self) -> None:
        require_loopback_host("127.0.0.1")
        require_loopback_host("::1")
        with self.assertRaises(ValueError):
            require_loopback_host("0.0.0.0")
        with self.assertRaises(ValueError):
            require_loopback_host("192.168.1.10")
        self.assertEqual({ALLOWED_ORIGIN}, parse_extension_origins(ALLOWED_ORIGIN))
        with self.assertRaises(ValueError):
            parse_extension_origins("https://example.test")
        with self.assertRaises(ValueError):
            parse_extension_origins("")


if __name__ == "__main__":
    unittest.main()
