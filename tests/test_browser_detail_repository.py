import hashlib
import sqlite3
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, Optional

from social_content_engine.data.browser_observation import browser_observation_payload_sha256
from social_content_engine.data.repository import Repository


def observation(
    *, observation_type: str = "SEARCH_CARD", view_count: Optional[int] = None
) -> Dict[str, Any]:
    surface = (
        "threads_post_detail"
        if observation_type == "POST_DETAIL"
        else "threads_search_card"
    )
    value: Dict[str, Any] = {
        "schema_version": 1,
        "observation_type": observation_type,
        "source": "threads",
        "post_url": "https://www.threads.net/@fixture/post/Detail123",
        "source_post_id": None,
        "author_name": "Fixture",
        "username": "fixture",
        "text": "synthetic public post",
        "timestamp": "2026-08-16T00:00:00+00:00",
        "public_counters": {
            "view_count": view_count,
            "like_count": 0,
            "reply_count": None,
            "repost_count": None,
            "quote_count": None,
            "share_count": None,
        },
        "media_type": "TEXT_POST",
        "has_image": False,
        "has_video": False,
        "collection_context": {
            "surface": surface,
            "page_url": "https://www.threads.net/search?q=fixture",
            "query": "fixture",
            "position": 0,
        },
        "observed_fields": [
            {
                "field": "text",
                "value": "synthetic public post",
                "surface": surface,
                "observed_at": "2026-08-16T00:00:00+00:00",
                "extractor_version": "fixture-extractor-v1",
            }
        ],
        "collected_at": "2026-08-16T00:00:01+00:00",
        "extractor_version": "fixture-extractor-v1",
    }
    if view_count is not None:
        value["observed_fields"].append(
            {
                "field": "public_counters.view_count",
                "value": view_count,
                "surface": surface,
                "observed_at": "2026-08-16T00:00:00+00:00",
                "extractor_version": "fixture-extractor-v1",
            }
        )
    value["payload_sha256"] = browser_observation_payload_sha256(value)
    return value


def downgrade_before_migration_9(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.execute("DROP TABLE browser_detail_failures")
    connection.execute("DROP TABLE browser_detail_attempts")
    connection.execute("DELETE FROM schema_migrations WHERE version = 9")
    connection.commit()
    connection.close()


class BrowserDetailRepositoryTest(unittest.TestCase):
    def test_thread_sequence_observation_is_append_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with Repository(Path(directory) / "sequence.sqlite3") as repository:
                root = repository.add_browser_observation(observation())
                detail = repository.add_browser_observation(
                    observation(observation_type="POST_DETAIL")
                )
                sequence_id = repository.record_browser_thread_sequence_observation(
                    root_identity_id=root["browser_post_identity_id"],
                    node_identity_id=root["browser_post_identity_id"],
                    reply_to_identity_id=None, sequence_position=0,
                    same_author_as_root=None,
                    detail_observation_id=detail["browser_observation_id"],
                    extractor_version="fixture-sequence-v1",
                )
                row = repository.connection.execute(
                    "SELECT * FROM browser_thread_sequence_observations WHERE id = ?",
                    (sequence_id,),
                ).fetchone()
                self.assertIsNone(row["same_author_as_root"])
                with self.assertRaises(sqlite3.IntegrityError):
                    repository.connection.execute(
                        "UPDATE browser_thread_sequence_observations "
                        "SET sequence_position = 1 WHERE id = ?",
                        (sequence_id,),
                    )
    def test_success_and_failure_history_is_append_only_and_fk_valid(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with Repository(Path(directory) / "detail.sqlite3") as repository:
                repository.add_browser_observation(observation())
                detail = repository.add_browser_observation(
                    observation(observation_type="POST_DETAIL", view_count=31)
                )
                repository.record_browser_detail_success(
                    browser_observation_id=detail["browser_observation_id"],
                    attempted_at="2026-08-16T00:01:00+00:00",
                    extractor_version="detail-extractor-v1",
                )
                repository.record_browser_detail_failure(
                    post_url=detail["post_url"],
                    attempted_at="2026-08-16T00:02:00+00:00",
                    extractor_version="detail-extractor-v1",
                    failure_type="TIMEOUT",
                    failure_reason="TIME_LIMIT_EXCEEDED",
                )
                self.assertEqual(2, repository.count("browser_detail_attempts"))
                self.assertEqual(1, repository.count("browser_detail_failures"))
                self.assertEqual(2, repository.count("browser_observations"))
                self.assertEqual(
                    ["SUCCEEDED", "FAILED"],
                    [
                        row[0]
                        for row in repository.connection.execute(
                            "SELECT outcome FROM browser_detail_attempts ORDER BY id"
                        ).fetchall()
                    ],
                )
                self.assertEqual(
                    [], repository.connection.execute("PRAGMA foreign_key_check").fetchall()
                )
                with self.assertRaisesRegex(sqlite3.IntegrityError, "immutable"):
                    repository.connection.execute(
                        "UPDATE browser_detail_attempts SET attempted_at = 'changed'"
                    )

    def test_failure_is_latest_state_without_erasing_evidence_or_downgrading_enriched(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with Repository(Path(directory) / "state.sqlite3") as repository:
                first = repository.add_browser_observation(observation())
                repository.record_browser_detail_failure(
                    post_url=first["post_url"],
                    attempted_at="2026-08-16T00:01:00Z",
                    extractor_version="detail-extractor-v1",
                    failure_type="PAGE_UNAVAILABLE",
                    failure_reason="POST_NOT_FOUND",
                )
                repository.add_browser_observation(observation())
                self.assertEqual(
                    "DETAIL_FAILED",
                    repository.connection.execute(
                        "SELECT status FROM browser_post_identities"
                    ).fetchone()[0],
                )
                detail = repository.add_browser_observation(
                    observation(observation_type="POST_DETAIL", view_count=44)
                )
                repository.record_browser_detail_success(
                    browser_observation_id=detail["browser_observation_id"],
                    attempted_at="2026-08-16T00:02:00Z",
                    extractor_version="detail-extractor-v1",
                )
                repository.record_browser_detail_failure(
                    post_url=detail["post_url"],
                    attempted_at="2026-08-16T00:03:00Z",
                    extractor_version="detail-extractor-v1",
                    failure_type="EXTRACTION_FAILED",
                    failure_reason="EXPECTED_FIELD_MISSING",
                )
                repository.add_browser_observation(observation())
                identity = repository.connection.execute(
                    "SELECT status, current_observation_id FROM browser_post_identities"
                ).fetchone()
                self.assertEqual("DETAIL_ENRICHED", identity["status"])
                self.assertEqual(4, repository.count("browser_observations"))
                self.assertEqual(2, repository.count("browser_detail_failures"))

    def test_contract_is_closed_and_stores_no_free_form_or_browser_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with Repository(Path(directory) / "closed.sqlite3") as repository:
                saved = repository.add_browser_observation(observation())
                for failure_type, failure_reason in (
                    ("DOM_FAILED", "UNRECOGNIZED_PAGE"),
                    ("TIMEOUT", "cookie=secret"),
                ):
                    with self.subTest(failure_type=failure_type, reason=failure_reason):
                        with self.assertRaisesRegex(ValueError, "invalid"):
                            repository.record_browser_detail_failure(
                                post_url=saved["post_url"],
                                attempted_at="2026-08-16T00:01:00Z",
                                extractor_version="detail-extractor-v1",
                                failure_type=failure_type,
                                failure_reason=failure_reason,
                            )
                with self.assertRaisesRegex(ValueError, "timezone"):
                    repository.record_browser_detail_failure(
                        post_url=saved["post_url"],
                        attempted_at="2026-08-16T00:01:00",
                        extractor_version="detail-extractor-v1",
                        failure_type="TIMEOUT",
                        failure_reason="TIME_LIMIT_EXCEEDED",
                    )
                columns = {
                    str(row[1]).lower()
                    for table in ("browser_detail_attempts", "browser_detail_failures")
                    for row in repository.connection.execute(
                        "PRAGMA table_info(" + table + ")"
                    ).fetchall()
                }
                self.assertTrue(
                    {"cookie", "token", "password", "dom", "html", "failure_detail"}.isdisjoint(
                        columns
                    )
                )
                self.assertEqual(0, repository.count("browser_detail_attempts"))

    def test_success_requires_matching_post_detail_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with Repository(Path(directory) / "success.sqlite3") as repository:
                search = repository.add_browser_observation(observation())
                with self.assertRaisesRegex(ValueError, "POST_DETAIL"):
                    repository.record_browser_detail_success(
                        browser_observation_id=search["browser_observation_id"],
                        attempted_at="2026-08-16T00:01:00Z",
                        extractor_version="detail-extractor-v1",
                    )
                with self.assertRaisesRegex(ValueError, "contract version"):
                    repository.record_browser_detail_failure(
                        post_url=search["post_url"],
                        attempted_at="2026-08-16T00:01:00Z",
                        extractor_version="detail-extractor-v1",
                        contract_version="future-contract",
                        failure_type="TIMEOUT",
                        failure_reason="TIME_LIMIT_EXCEEDED",
                    )

    def test_migration_9_checksum_idempotency_and_atomic_rollback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.sqlite3"
            with Repository(path):
                pass
            downgrade_before_migration_9(path)
            with Repository(path) as repository:
                migration = repository.connection.execute(
                    "SELECT migration_sha256 FROM schema_migrations WHERE version = 9"
                ).fetchone()
                self.assertIsNotNone(migration)
                expected = hashlib.sha256(
                    b"9:browser-detail-attempt-failure-history-v1"
                ).hexdigest()
                self.assertEqual(expected, migration[0])
            with Repository(path) as repository:
                self.assertEqual(
                    1,
                    repository.connection.execute(
                        "SELECT COUNT(*) FROM schema_migrations WHERE version = 9"
                    ).fetchone()[0],
                )

            conflict = Path(directory) / "conflict.sqlite3"
            with Repository(conflict):
                pass
            downgrade_before_migration_9(conflict)
            connection = sqlite3.connect(conflict)
            connection.execute("CREATE TABLE browser_detail_attempts (id INTEGER PRIMARY KEY)")
            connection.commit()
            connection.close()
            with self.assertRaises(sqlite3.OperationalError):
                Repository(conflict)
            connection = sqlite3.connect(conflict)
            try:
                self.assertIsNone(
                    connection.execute(
                        "SELECT name FROM sqlite_master WHERE name = 'browser_detail_failures'"
                    ).fetchone()
                )
                self.assertEqual(
                    0,
                    connection.execute(
                        "SELECT COUNT(*) FROM schema_migrations WHERE version = 9"
                    ).fetchone()[0],
                )
            finally:
                connection.close()

    def test_migration_checksum_drift_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "checksum.sqlite3"
            with Repository(path):
                pass
            connection = sqlite3.connect(path)
            connection.execute(
                "UPDATE schema_migrations SET migration_sha256 = 'wrong' WHERE version = 9"
            )
            connection.commit()
            connection.close()
            with self.assertRaisesRegex(RuntimeError, "checksum mismatch"):
                Repository(path)


if __name__ == "__main__":
    unittest.main()
