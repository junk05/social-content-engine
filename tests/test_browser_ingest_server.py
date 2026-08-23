import copy
import http.client
import json
import tempfile
import threading
import unittest
from http.server import HTTPServer
from pathlib import Path

from social_content_engine.browser_ingest.server import (
    COLLECTED_POSTS_PATH,
    DETAIL_BATCHES_PATH,
    DETAIL_EXCLUSION_PATH,
    DETAIL_FAILURE_PATH,
    DETAIL_QUEUE_CLAIM_PATH,
    DETAIL_QUEUE_COMPLETE_PATH,
    DETAIL_QUEUE_FAIL_PATH,
    DETAIL_QUEUE_SUMMARY_PATH,
    INGEST_PATH,
    MAX_BODY_BYTES,
    NATIVE_INPUT_MOVE_PATH,
    NATIVE_INPUT_SPIKE_PATH,
    PENDING_DETAILS_PATH,
    REVIEW_EXPORT_PATH,
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
        self.service = BrowserIngestService(self.repository, {ALLOWED_ORIGIN}, load_schema())

    def post(self, payload: dict, **kwargs: str):
        return self.service.handle_post(
            "/browser-ingest/threads",
            kwargs.get("origin", ALLOWED_ORIGIN),
            kwargs.get("content_type", "application/json"),
            json.dumps(payload).encode("utf-8"),
        )

    def observed_url(self, post_code: str, **kwargs: object) -> dict:
        payload = observation(**kwargs)
        payload["post_url"] = "https://www.threads.net/@fixture/post/" + post_code
        payload["payload_sha256"] = browser_observation_payload_sha256(payload)
        return payload

    def test_options_success_and_duplicate_observation(self) -> None:
        preflight = self.service.handle_options("/browser-ingest/threads", ALLOWED_ORIGIN)
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

    def test_accepts_direct_publication_time_with_explicit_offset(self) -> None:
        payload = observation(
            observation_type="POST_DETAIL", metric_statuses=True,
            timestamp="2026-08-22T09:15:00+09:00",
            published_at_raw="2026-08-22T09:15:00+09:00",
            published_at="2026-08-22T09:15:00+09:00",
            published_timezone_basis="TIME_DATETIME_EXPLICIT_OFFSET",
        )
        accepted = self.post(payload)
        self.assertEqual(201, accepted.status)
        stored = self.repository.connection.execute(
            "SELECT canonical_payload_json FROM browser_observations"
        ).fetchone()
        self.assertEqual(
            "2026-08-22T09:15:00+09:00",
            json.loads(str(stored["canonical_payload_json"]))["published_at"],
        )

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

    def test_native_input_spike_is_extension_only_shape_closed_and_one_shot(self) -> None:
        clicks = []
        self.service.native_click_runner = lambda x, y: clicks.append((x, y)) or "clicked"
        first = self.service.handle_post(
            NATIVE_INPUT_SPIKE_PATH, ALLOWED_ORIGIN, "application/json", b'{"x":12.5,"y":30}'
        )
        self.assertEqual(200, first.status)
        self.assertEqual({"status": "clicked"}, first.payload)
        self.assertEqual([(12.5, 30.0)], clicks)
        second = self.service.handle_post(
            NATIVE_INPUT_SPIKE_PATH, ALLOWED_ORIGIN, "application/json", b'{"x":13,"y":31}'
        )
        self.assertEqual(422, second.status)
        self.assertEqual([], clicks[1:])

    def test_native_input_move_is_shape_closed_and_one_shot(self) -> None:
        moves = []
        self.service.native_move_runner = lambda x, y: moves.append((x, y)) or "cursor_moved"
        first = self.service.handle_post(
            NATIVE_INPUT_MOVE_PATH,
            ALLOWED_ORIGIN,
            "application/json",
            b'{"action":"move_cursor","x":-120.5,"y":30}',
        )
        self.assertEqual(200, first.status)
        self.assertEqual({"status": "cursor_moved"}, first.payload)
        self.assertEqual([(-120.5, 30.0)], moves)
        second = self.service.handle_post(
            NATIVE_INPUT_MOVE_PATH,
            ALLOWED_ORIGIN,
            "application/json",
            b'{"action":"move_cursor","x":13,"y":31}',
        )
        self.assertEqual(422, second.status)
        rejected = BrowserIngestService(
            self.repository, {ALLOWED_ORIGIN}, load_schema()
        ).handle_post(
            NATIVE_INPUT_MOVE_PATH,
            ALLOWED_ORIGIN,
            "application/json",
            b'{"action":"click","x":13,"y":31}',
        )
        self.assertEqual(422, rejected.status)
        self.assertEqual({"status": "unavailable"}, rejected.payload)

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
        server = HTTPServer(("127.0.0.1", 0), configured_handler(http_service))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=2)
        try:
            connection.request(
                "OPTIONS",
                "/browser-ingest/threads",
                headers={"Origin": ALLOWED_ORIGIN},
            )
            preflight = connection.getresponse()
            self.assertEqual(204, preflight.status)
            self.assertEqual(ALLOWED_ORIGIN, preflight.getheader("Access-Control-Allow-Origin"))
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
            self.assertEqual(ALLOWED_ORIGIN, accepted.getheader("Access-Control-Allow-Origin"))
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
        self.post(self.observed_url("Enriched", observation_type="POST_DETAIL", view_count=None))
        response = self.service.handle_get(PENDING_DETAILS_PATH, "limit=1", ALLOWED_ORIGIN)
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
            self.service.handle_get(PENDING_DETAILS_PATH, "limit=101", ALLOWED_ORIGIN).status,
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
        detail = self.observed_url(
            "DetailMissingView",
            observation_type="POST_DETAIL",
            view_count=None,
            metric_statuses=True,
        )
        accepted = self.post(detail)
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
        statuses = self.repository.connection.execute(
            """SELECT field_name, observation_status
            FROM browser_metric_observation_statuses
            WHERE browser_observation_id = ?""",
            (accepted.payload["observation_id"],),
        ).fetchall()
        self.assertIn(
            ("public_counters.view_count", "NOT_PRESENT"),
            [tuple(row) for row in statuses],
        )

    def test_post_detail_accepts_rounded_views_without_exact_view_count(self) -> None:
        rounded = {
            "display": "表示3.3万回",
            "normalized_approx": 33000,
            "precision": "ROUNDED",
            "source": "POST_DETAIL_PAGE",
            "view_band": "10K_100K",
            "observed_at": "2026-08-16T00:00:01+00:00",
            "extractor_version": "fixture-extractor-v1",
            "normalizer_version": "rounded-views-normalizer-v1",
        }
        accepted = self.post(
            self.observed_url(
                "RoundedViews",
                observation_type="POST_DETAIL",
                view_count=None,
                metric_statuses=True,
                approximate_views=rounded,
            )
        )
        self.assertEqual(201, accepted.status)
        self.assertEqual("DETAIL_ENRICHED", accepted.payload["observation_status"])
        row = self.repository.connection.execute(
            "SELECT * FROM browser_approximate_view_observations"
        ).fetchone()
        self.assertEqual(33000, row["normalized_approx"])
        self.assertEqual("ROUNDED", row["precision"])

    def test_post_detail_accepts_exact_integer_display_views(self) -> None:
        displayed = {
            "display": "表示4,506回",
            "normalized_value": 4506,
            "precision": "DISPLAY_EXACT",
            "source": "POST_DETAIL_PAGE",
            "view_band": "1K_10K",
            "observed_at": "2026-08-16T00:00:01+00:00",
            "extractor_version": "fixture-extractor-v1",
            "normalizer_version": "display-views-normalizer-v1",
        }
        accepted = self.post(
            self.observed_url(
                "DisplayViews",
                observation_type="POST_DETAIL",
                view_count=None,
                metric_statuses=True,
                display_views=displayed,
            )
        )
        self.assertEqual(201, accepted.status)
        self.assertEqual("DETAIL_ENRICHED", accepted.payload["observation_status"])
        row = self.repository.connection.execute(
            "SELECT * FROM browser_display_view_observations"
        ).fetchone()
        self.assertEqual(4506, row["normalized_value"])
        self.assertEqual("DISPLAY_EXACT", row["precision"])

    def test_durable_queue_batch_claim_complete_and_summary(self) -> None:
        search = self.post(self.observed_url("QueueSuccess"))
        summary = self.service.handle_get(DETAIL_QUEUE_SUMMARY_PATH, "", ALLOWED_ORIGIN)
        self.assertEqual(200, summary.status)
        self.assertEqual(1, summary.payload["collected_count"])
        self.assertEqual(1, summary.payload["counts"]["DETAIL_PENDING"])
        started = self.service.handle_post(
            DETAIL_BATCHES_PATH,
            ALLOWED_ORIGIN,
            "application/json",
            json.dumps(
                {
                    "action": "start",
                    "requested_items": 1,
                    "max_items": 1,
                    "retry_failed": False,
                }
            ).encode("utf-8"),
        )
        self.assertEqual(200, started.status)
        batch_id = started.payload["batch_id"]
        claimed = self.service.handle_post(
            DETAIL_QUEUE_CLAIM_PATH,
            ALLOWED_ORIGIN,
            "application/json",
            json.dumps({"batch_id": batch_id}).encode("utf-8"),
        )
        self.assertEqual("claimed", claimed.payload["status"])
        self.assertEqual(self.observed_url("QueueSuccess")["post_url"], claimed.payload["post_url"])
        detail = self.post(
            self.observed_url("QueueSuccess", observation_type="POST_DETAIL", view_count=0)
        )
        completion = {
            "queue_item_id": claimed.payload["queue_item_id"],
            "batch_id": batch_id,
            "attempt": claimed.payload["attempt"],
            "lease_version": claimed.payload["lease_version"],
            "detail_observation_id": detail.payload["observation_id"],
        }
        completed = self.service.handle_post(
            DETAIL_QUEUE_COMPLETE_PATH,
            ALLOWED_ORIGIN,
            "application/json",
            json.dumps(completion).encode("utf-8"),
        )
        self.assertEqual(200, completed.status)
        empty = self.service.handle_post(
            DETAIL_QUEUE_CLAIM_PATH,
            ALLOWED_ORIGIN,
            "application/json",
            json.dumps({"batch_id": batch_id}).encode("utf-8"),
        )
        self.assertEqual("empty", empty.payload["status"])
        finished = self.service.handle_post(
            DETAIL_BATCHES_PATH,
            ALLOWED_ORIGIN,
            "application/json",
            json.dumps(
                {
                    "action": "finish",
                    "batch_id": batch_id,
                    "stopped": False,
                }
            ).encode("utf-8"),
        )
        self.assertEqual("COMPLETED", finished.payload["batch_status"])
        self.assertEqual(search.payload["identity_id"], detail.payload["identity_id"])

    def test_collected_root_list_exclusion_and_requeue_are_closed_and_non_destructive(self) -> None:
        first = self.observed_url("ReviewA")
        second = self.observed_url("ReviewB")
        self.post(first)
        self.post(second)
        observation_count = self.repository.count("browser_observations")

        listed = self.service.handle_get(
            COLLECTED_POSTS_PATH, "status=ALL&sort=newest&limit=20", ALLOWED_ORIGIN
        )
        self.assertEqual(200, listed.status)
        self.assertEqual(2, listed.payload["count"])
        self.assertEqual(
            {
                "collected_at",
                "author_username",
                "post_url",
                "detail_status",
                "attempt_count",
                "last_error",
                "views_latest_raw",
                "views_latest_value",
                "views_latest_precision",
                "views_latest_display_format",
                "views_latest_observed_at",
                "views_latest_band",
                "self_reply_count",
                "enrichment_excluded",
                "exclusion_reason",
                "excluded_at",
            },
            set(listed.payload["posts"][0]),
        )
        self.assertIsNone(listed.payload["posts"][0]["views_latest_value"])
        self.assertIsNone(listed.payload["posts"][0]["self_reply_count"])
        self.assertNotIn("source_text", listed.body.decode("utf-8"))

        excluded = self.service.handle_post(
            DETAIL_EXCLUSION_PATH,
            ALLOWED_ORIGIN,
            "application/json",
            json.dumps({"action": "EXCLUDE", "post_url": second["post_url"]}).encode(),
        )
        self.assertEqual(200, excluded.status)
        self.assertTrue(excluded.payload["enrichment_excluded"])
        excluded_list = self.service.handle_get(
            COLLECTED_POSTS_PATH, "status=EXCLUDED", ALLOWED_ORIGIN
        )
        self.assertEqual(1, excluded_list.payload["count"])
        self.assertEqual("EXCLUDED", excluded_list.payload["posts"][0]["detail_status"])
        pending = self.service.handle_get(PENDING_DETAILS_PATH, "limit=10", ALLOWED_ORIGIN)
        self.assertEqual([first["post_url"]], pending.payload["urls"])

        requeued = self.service.handle_post(
            DETAIL_EXCLUSION_PATH,
            ALLOWED_ORIGIN,
            "application/json",
            json.dumps({"action": "REQUEUE", "post_url": second["post_url"]}).encode(),
        )
        self.assertEqual(200, requeued.status)
        self.assertFalse(requeued.payload["enrichment_excluded"])
        pending_list = self.service.handle_get(
            COLLECTED_POSTS_PATH, "status=DETAIL_PENDING", ALLOWED_ORIGIN
        )
        self.assertEqual(2, pending_list.payload["count"])
        self.assertEqual(observation_count, self.repository.count("browser_observations"))
        self.assertEqual(2, self.repository.count("browser_detail_enrichment_exclusion_actions"))
        invalid = self.service.handle_post(
            DETAIL_EXCLUSION_PATH,
            ALLOWED_ORIGIN,
            "application/json",
            json.dumps({"action": "DELETE", "post_url": second["post_url"]}).encode(),
        )
        self.assertEqual(422, invalid.status)
        self.assertEqual(
            400,
            self.service.handle_get(COLLECTED_POSTS_PATH, "status=UNKNOWN", ALLOWED_ORIGIN).status,
        )

    def test_review_csv_download_is_filtered_bom_safe_and_read_only(self) -> None:
        selected = self.observed_url("CsvReview", text="日本語の監査本文")
        self.assertEqual(201, self.post(selected).status)
        changes_before = self.repository.connection.total_changes
        posts = self.service.handle_get(
            REVIEW_EXPORT_PATH,
            "kind=POSTS&status=DETAIL_PENDING",
            ALLOWED_ORIGIN,
        )
        threads = self.service.handle_get(
            REVIEW_EXPORT_PATH,
            "kind=THREAD_NODES&status=DETAIL_PENDING",
            ALLOWED_ORIGIN,
        )
        self.assertEqual(changes_before, self.repository.connection.total_changes)
        self.assertEqual(200, posts.status)
        self.assertEqual("text/csv; charset=utf-8", posts.content_type)
        self.assertEqual('attachment; filename="threads_posts.csv"', posts.content_disposition)
        self.assertTrue(posts.body.startswith(b"\xef\xbb\xbf"))
        rendered = posts.body.decode("utf-8-sig")
        self.assertIn("日本語の監査本文", rendered)
        self.assertIn(selected["post_url"], rendered)
        self.assertEqual(200, threads.status)
        self.assertIn("root_canonical_id", threads.body.decode("utf-8-sig"))
        self.assertEqual(
            400,
            self.service.handle_get(
                REVIEW_EXPORT_PATH, "kind=POSTS&status=UNKNOWN", ALLOWED_ORIGIN
            ).status,
        )
        self.assertEqual(
            403,
            self.service.handle_get(
                REVIEW_EXPORT_PATH,
                "kind=POSTS&status=ALL",
                "chrome-extension://pppppppppppppppppppppppppppppppp",
            ).status,
        )

    def test_queue_failure_is_correlated_and_next_item_remains_claimable(self) -> None:
        self.post(self.observed_url("QueueFailure"))
        self.post(self.observed_url("QueueNext"))
        started = self.service.handle_post(
            DETAIL_BATCHES_PATH,
            ALLOWED_ORIGIN,
            "application/json",
            json.dumps(
                {
                    "action": "start",
                    "requested_items": 2,
                    "max_items": 2,
                    "retry_failed": False,
                }
            ).encode("utf-8"),
        )
        batch_id = started.payload["batch_id"]
        first = self.service.handle_post(
            DETAIL_QUEUE_CLAIM_PATH,
            ALLOWED_ORIGIN,
            "application/json",
            json.dumps({"batch_id": batch_id}).encode("utf-8"),
        ).payload
        failure = {
            "queue_item_id": first["queue_item_id"],
            "batch_id": batch_id,
            "attempt": first["attempt"],
            "lease_version": first["lease_version"],
            "attempted_at": "2026-08-16T05:00:00Z",
            "extractor_version": "threads-post-detail-extractor-v2",
            "contract_version": "M3_BROWSER_DETAIL_ATTEMPT_V1",
            "failure_type": "TIMEOUT",
            "failure_reason": "TIME_LIMIT_EXCEEDED",
            "error_code": "ACTIVITY_DIALOG_TIMEOUT",
        }
        failed = self.service.handle_post(
            DETAIL_QUEUE_FAIL_PATH,
            ALLOWED_ORIGIN,
            "application/json",
            json.dumps(failure).encode("utf-8"),
        )
        self.assertEqual(201, failed.status)
        stale = dict(failure)
        stale["attempted_at"] = "2026-08-16T05:01:00Z"
        self.assertEqual(
            422,
            self.service.handle_post(
                DETAIL_QUEUE_FAIL_PATH,
                ALLOWED_ORIGIN,
                "application/json",
                json.dumps(stale).encode("utf-8"),
            ).status,
        )
        second = self.service.handle_post(
            DETAIL_QUEUE_CLAIM_PATH,
            ALLOWED_ORIGIN,
            "application/json",
            json.dumps({"batch_id": batch_id}).encode("utf-8"),
        )
        self.assertEqual("claimed", second.payload["status"])
        self.assertNotEqual(first["queue_item_id"], second.payload["queue_item_id"])

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
        child_detail = self.post(self.observed_url("SequenceChild", observation_type="POST_DETAIL"))
        detail = self.post(self.observed_url("SequenceRoot", observation_type="POST_DETAIL"))
        payload = {
            "root_post_url": root["post_url"],
            "detail_observation_id": detail.payload["observation_id"],
            "observed_at": "2026-08-16T04:00:00Z",
            "extractor_version": "fixture-sequence-v1",
            "thread_extraction": {
                "diagnostic_version": "fixture-thread-diagnostic-v1",
                "visible_post_nodes": 2,
                "discovered_candidates": 2,
                "direct_root_author_candidates": 1,
                "other_author_candidates": 0,
                "root_author_after_other_boundary": 0,
                "final_eligible_nodes": 2,
                "excluded_candidates": 0,
                "exclusion_reasons": {},
            },
            "nodes": [
                {
                    "post_url": root["post_url"],
                    "sequence_position": 0,
                    "reply_to_post_url": None,
                    "same_author_as_root": True,
                    "relationship_evidence": "ROOT_DETAIL_PAGE",
                },
                {
                    "post_url": child["post_url"],
                    "sequence_position": 1,
                    "reply_to_post_url": root["post_url"],
                    "same_author_as_root": True,
                    "relationship_evidence": "DOM_CONTIGUOUS_ROOT_AUTHOR_CHAIN",
                },
            ],
        }
        accepted = self.service.handle_post(
            THREAD_SEQUENCE_PATH,
            ALLOWED_ORIGIN,
            "application/json",
            json.dumps(payload).encode("utf-8"),
        )
        self.assertEqual(201, accepted.status)
        self.assertEqual(
            {"status": "accepted", "node_count": 2,
             "thread_extraction_status": "NOT_APPLICABLE"}, accepted.payload
        )
        self.assertEqual(2, self.repository.count("browser_thread_sequence_observations"))
        child_identity = self.repository.connection.execute(
            "SELECT id FROM browser_post_identities WHERE post_url = ?", (child["post_url"],)
        ).fetchone()[0]
        self.assertEqual(
            child_detail.payload["observation_id"],
            self.repository.connection.execute(
                """SELECT current_observation_id FROM browser_post_identities WHERE id = ?""",
                (child_identity,),
            ).fetchone()[0],
        )
        relationship = self.repository.connection.execute(
            """SELECT reply_to_browser_post_identity_id, sequence_position,
                      same_author_as_root, relationship_evidence
               FROM browser_thread_sequence_observations
               WHERE node_browser_post_identity_id = ?""",
            (child_identity,),
        ).fetchone()
        self.assertIsNotNone(relationship["reply_to_browser_post_identity_id"])
        self.assertEqual(1, relationship["sequence_position"])
        self.assertEqual(1, relationship["same_author_as_root"])
        self.assertEqual("DOM_CONTIGUOUS_ROOT_AUTHOR_CHAIN", relationship["relationship_evidence"])
        bad_detail = dict(payload)
        bad_detail["detail_observation_id"] = 1
        rejected = self.service.handle_post(
            THREAD_SEQUENCE_PATH,
            ALLOWED_ORIGIN,
            "application/json",
            json.dumps(bad_detail).encode("utf-8"),
        )
        self.assertEqual(422, rejected.status)
        self.assertEqual(2, self.repository.count("browser_thread_sequence_observations"))
        bad_node = dict(payload)
        bad_node["detail_observation_id"] = detail.payload["observation_id"]
        bad_node["nodes"] = [
            payload["nodes"][0],
            {
                "post_url": "https://www.threads.net/@fixture/post/UnknownChild",
                "sequence_position": 1,
                "reply_to_post_url": root["post_url"],
                "same_author_as_root": None,
                "relationship_evidence": "DOM_CONTIGUOUS_ROOT_AUTHOR_CHAIN",
            },
        ]
        self.assertEqual(
            422,
            self.service.handle_post(
                THREAD_SEQUENCE_PATH,
                ALLOWED_ORIGIN,
                "application/json",
                json.dumps(bad_node).encode("utf-8"),
            ).status,
        )
        self.assertEqual(2, self.repository.count("browser_thread_sequence_observations"))
        bad_evidence = json.loads(json.dumps(payload))
        bad_evidence["nodes"][1]["relationship_evidence"] = "USERNAME_ONLY"
        self.assertEqual(
            422,
            self.service.handle_post(
                THREAD_SEQUENCE_PATH,
                ALLOWED_ORIGIN,
                "application/json",
                json.dumps(bad_evidence).encode("utf-8"),
            ).status,
        )
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
            self.post(
                observation(), origin="chrome-extension://pppppppppppppppppppppppppppppppp"
            ).status,
        )
        self.assertEqual(415, self.post(observation(), content_type="text/plain").status)
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
