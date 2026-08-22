import hashlib
import sqlite3
import tempfile
import unittest
from pathlib import Path

from social_content_engine.data.browser_observation import browser_observation_payload_sha256
from social_content_engine.data.repository import Repository
from tests.test_browser_detail_repository import observation


def downgrade_before_migration_16(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.execute("DROP TABLE browser_detail_batch_assignments")
    connection.execute("DROP TABLE browser_approximate_view_observations")
    connection.execute("DROP TABLE browser_metric_observation_statuses")
    connection.execute("DROP TABLE browser_detail_enrichment_queue")
    connection.execute("DROP TABLE browser_detail_enrichment_batches")
    connection.execute("DELETE FROM schema_migrations WHERE version >= 16")
    connection.commit()
    connection.close()


def prepare_before_assignment_reconciliation(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.execute("DROP TRIGGER immutable_browser_detail_batch_assignments_update")
    connection.execute("DROP TRIGGER immutable_browser_detail_batch_assignments_delete")
    connection.execute("DELETE FROM browser_detail_batch_assignments")
    connection.execute("DELETE FROM schema_migrations WHERE version = 22")
    connection.commit()
    connection.close()


class BrowserDetailQueueRepositoryTest(unittest.TestCase):
    def test_migration_22_reconciles_assignment_from_pre_migration_receiver(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "assignment-reconcile.sqlite3"
            with Repository(path) as repository:
                repository.add_browser_observation(observation())
            prepare_before_assignment_reconciliation(path)
            connection = sqlite3.connect(path)
            batch = connection.execute(
                """INSERT INTO browser_detail_enrichment_batches
                (status, requested_items, max_items, started_at, completed_at)
                VALUES ('COMPLETED', 1, 1, '2026-08-22T00:00:00Z',
                        '2026-08-22T00:01:00Z')"""
            ).lastrowid
            connection.execute(
                """UPDATE browser_detail_enrichment_queue SET
                active_batch_id = ?, attempt_count = 1, lease_version = 1,
                updated_at = '2026-08-22T00:00:30Z'""",
                (batch,),
            )
            connection.commit()
            connection.close()

            with Repository(path) as repository:
                assignment = repository.connection.execute(
                    "SELECT * FROM browser_detail_batch_assignments"
                ).fetchone()
                self.assertEqual(batch, assignment["browser_detail_batch_id"])
                self.assertEqual(1, assignment["attempt_count"])
                self.assertEqual(1, assignment["lease_version"])

    def test_requeue_only_latest_enriched_invalid_date_text(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with Repository(Path(directory) / "requeue.sqlite3") as repository:
                search = repository.add_browser_observation(observation())
                queue_id = int(
                    repository.connection.execute(
                        "SELECT id FROM browser_detail_enrichment_queue"
                    ).fetchone()[0]
                )
                batch_id = repository.start_browser_detail_batch(
                    requested_items=1, max_items=1
                )
                claimed = repository.claim_browser_detail(batch_id)
                detail_payload = observation(observation_type="POST_DETAIL", view_count=None)
                detail_payload["text"] = "2026/08/16"
                detail_payload["observed_fields"][0]["value"] = "2026/08/16"
                detail_payload["payload_sha256"] = browser_observation_payload_sha256(
                    detail_payload
                )
                detail = repository.add_browser_observation(
                    detail_payload,
                    detail_attempt={
                        "attempted_at": "2026-08-22T04:59:00Z",
                        "extractor_version": "detail-extractor-v3",
                        "contract_version": "M3_BROWSER_DETAIL_ATTEMPT_V1",
                    },
                )
                repository.complete_browser_detail_queue(
                    queue_id,
                    batch_id=batch_id,
                    attempt=claimed["attempt"],
                    lease_version=claimed["lease_version"],
                    detail_observation_id=detail["browser_observation_id"],
                )
                repository.finish_browser_detail_batch(batch_id)
                repository.assess_browser_text_quality(
                    browser_observation_id=detail["browser_observation_id"],
                    quality_status="INVALID_TEXT_DATE_METADATA",
                    input_sha256="0" * 64,
                )

                self.assertEqual(
                    1,
                    repository.requeue_invalid_browser_detail_text(
                        requeued_at="2026-08-22T05:00:00Z"
                    ),
                )
                queue = repository.connection.execute(
                    "SELECT * FROM browser_detail_enrichment_queue WHERE id = ?", (queue_id,)
                ).fetchone()
                identity = repository.connection.execute(
                    "SELECT * FROM browser_post_identities WHERE post_url = ?",
                    (search["post_url"],),
                ).fetchone()
                self.assertEqual("DETAIL_PENDING", queue["status"])
                self.assertEqual("DETAIL_PENDING", identity["status"])
                self.assertEqual(2, repository.count("browser_observations"))
                self.assertEqual(1, repository.count("browser_text_quality_assessments"))
                self.assertEqual(1, queue["attempt_count"])
                self.assertIsNotNone(queue["last_attempt_id"])
                assignment = repository.connection.execute(
                    """SELECT * FROM browser_detail_batch_assignments
                    WHERE browser_detail_queue_id = ?""",
                    (queue_id,),
                ).fetchone()
                self.assertEqual(batch_id, assignment["browser_detail_batch_id"])
                with self.assertRaisesRegex(sqlite3.IntegrityError, "immutable"):
                    repository.connection.execute(
                        """DELETE FROM browser_detail_batch_assignments WHERE id = ?""",
                        (assignment["id"],),
                    )
                self.assertEqual(0, repository.requeue_invalid_browser_detail_text())

    def test_migration_18_backfills_existing_selected_pending_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "backfill.sqlite3"
            with Repository(path) as repository:
                saved = repository.add_browser_observation(observation())
                self.assertEqual(1, repository.count("browser_detail_enrichment_queue"))
            connection = sqlite3.connect(path)
            connection.execute("DELETE FROM browser_detail_enrichment_queue")
            connection.execute("DELETE FROM schema_migrations WHERE version = 18")
            connection.commit()
            connection.close()
            with Repository(path) as repository:
                queued = repository.connection.execute(
                    "SELECT * FROM browser_detail_enrichment_queue"
                ).fetchall()
                self.assertEqual(1, len(queued))
                self.assertEqual("DETAIL_PENDING", queued[0]["status"])
                self.assertEqual(
                    saved["browser_observation_id"], queued[0]["source_observation_id"]
                )
                self.assertEqual(1, repository.count("browser_observations"))
            with Repository(path) as repository:
                self.assertEqual(1, repository.count("browser_detail_enrichment_queue"))

    def test_migration_17_reconciles_multiple_running_batches(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "running.sqlite3"
            with Repository(path):
                pass
            connection = sqlite3.connect(path)
            connection.execute("DROP INDEX one_running_browser_detail_batch")
            connection.execute("DELETE FROM schema_migrations WHERE version = 17")
            connection.execute(
                """INSERT INTO browser_detail_enrichment_batches
                (status, requested_items, max_items, started_at)
                VALUES ('RUNNING', 1, 1, '2026-08-16T00:00:00Z')"""
            )
            connection.execute(
                """INSERT INTO browser_detail_enrichment_batches
                (status, requested_items, max_items, started_at)
                VALUES ('RUNNING', 1, 1, '2026-08-16T00:01:00Z')"""
            )
            connection.commit()
            connection.close()
            with Repository(path) as repository:
                statuses = [
                    row[0]
                    for row in repository.connection.execute(
                        "SELECT status FROM browser_detail_enrichment_batches ORDER BY id"
                    ).fetchall()
                ]
                self.assertEqual(["RUNNING", "STOPPED"], statuses)
                self.assertIsNotNone(
                    repository.connection.execute(
                        """SELECT name FROM sqlite_master
                        WHERE type = 'index' AND name = 'one_running_browser_detail_batch'"""
                    ).fetchone()
                )

    def test_duplicate_enqueue_claim_success_and_source_observation_preservation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with Repository(Path(directory) / "queue.sqlite3") as repository:
                search = repository.add_browser_observation(observation())
                automatically_queued = repository.connection.execute(
                    "SELECT * FROM browser_detail_enrichment_queue"
                ).fetchone()
                self.assertEqual("DETAIL_PENDING", automatically_queued["status"])
                self.assertEqual(
                    search["browser_observation_id"],
                    automatically_queued["source_observation_id"],
                )
                duplicate = repository.add_browser_observation(observation())
                self.assertNotEqual(
                    search["browser_observation_id"], duplicate["browser_observation_id"]
                )
                self.assertEqual(1, repository.count("browser_detail_enrichment_queue"))
                self.assertEqual(
                    search["browser_observation_id"],
                    repository.connection.execute(
                        "SELECT source_observation_id FROM browser_detail_enrichment_queue"
                    ).fetchone()[0],
                )
                queue_id = repository.enqueue_browser_detail(
                    search["post_url"], enqueued_at="2026-08-16T01:00:00Z"
                )
                self.assertEqual(queue_id, repository.enqueue_browser_detail(search["post_url"]))
                batch_id = repository.start_browser_detail_batch(
                    requested_items=1, max_items=1, started_at="2026-08-16T01:00:30Z"
                )
                self.assertEqual(
                    batch_id,
                    repository.start_browser_detail_batch(requested_items=1, max_items=1),
                )
                claimed = repository.claim_browser_detail(
                    batch_id, claimed_at="2026-08-16T01:01:00Z"
                )
                self.assertIsNotNone(claimed)
                self.assertEqual("DETAIL_PROCESSING", claimed["status"])
                self.assertEqual(1, claimed["attempt_count"])
                self.assertEqual(0, claimed["retry_count"])
                detail = repository.add_browser_observation(
                    observation(observation_type="POST_DETAIL", view_count=0),
                    detail_attempt={
                        "attempted_at": "2026-08-16T01:02:00Z",
                        "extractor_version": "detail-extractor-v1",
                        "contract_version": "M3_BROWSER_DETAIL_ATTEMPT_V1",
                    },
                )
                repository.complete_browser_detail_queue(
                    queue_id,
                    batch_id=batch_id,
                    attempt=claimed["attempt"],
                    lease_version=claimed["lease_version"],
                    detail_observation_id=detail["browser_observation_id"],
                    completed_at="2026-08-16T01:03:00Z",
                )
                repository.complete_browser_detail_queue(
                    queue_id,
                    batch_id=batch_id,
                    attempt=claimed["attempt"],
                    lease_version=claimed["lease_version"],
                    detail_observation_id=detail["browser_observation_id"],
                    completed_at="2026-08-16T01:03:01Z",
                )
                row = repository.connection.execute(
                    "SELECT * FROM browser_detail_enrichment_queue WHERE id = ?", (queue_id,)
                ).fetchone()
                self.assertEqual("DETAIL_ENRICHED", row["status"])
                self.assertEqual(search["browser_observation_id"], row["source_observation_id"])
                self.assertIsNotNone(row["last_attempt_id"])
                self.assertIsNone(repository.claim_browser_detail(batch_id))
                summary = repository.finish_browser_detail_batch(batch_id)
                self.assertEqual("COMPLETED", summary["status"])
                self.assertEqual(1, summary["counts"]["DETAIL_ENRICHED"])

    def test_failure_retry_and_crash_recovery_are_durable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "retry.sqlite3"
            with Repository(path) as repository:
                saved = repository.add_browser_observation(observation())
                queue_id = repository.enqueue_browser_detail(saved["post_url"])
                batch_id = repository.start_browser_detail_batch(
                    requested_items=1, max_items=1
                )
                first_claim = repository.claim_browser_detail(
                    batch_id, claimed_at="2026-08-16T02:00:00Z"
                )
                attempt_id = repository.fail_browser_detail_queue(
                    queue_id,
                    batch_id=batch_id,
                    attempt=first_claim["attempt"],
                    lease_version=first_claim["lease_version"],
                    attempted_at="2026-08-16T02:01:00Z",
                    extractor_version="detail-extractor-v1",
                    failure_type="TIMEOUT",
                    failure_reason="TIME_LIMIT_EXCEEDED",
                    error_code="PAGE_TIMEOUT",
                )
                failed = repository.connection.execute(
                    "SELECT * FROM browser_detail_enrichment_queue WHERE id = ?", (queue_id,)
                ).fetchone()
                self.assertEqual("DETAIL_FAILED", failed["status"])
                self.assertEqual(attempt_id, failed["last_attempt_id"])
                self.assertEqual("TIMEOUT", failed["last_error_type"])
                self.assertEqual("PAGE_TIMEOUT", failed["last_error_code"])
                repository.enqueue_browser_detail(saved["post_url"])
                retry_batch = repository.start_browser_detail_batch(
                    requested_items=1, max_items=1
                )
                retry = repository.claim_browser_detail(
                    retry_batch, claimed_at="2026-08-16T02:02:00Z"
                )
                self.assertEqual(2, retry["attempt_count"])
                self.assertEqual(1, retry["retry_count"])

            with Repository(path) as repository:
                resumed = repository.resume_browser_detail_batch(retry_batch)
                self.assertEqual("RUNNING", resumed["status"])
                recovered = repository.connection.execute(
                    "SELECT * FROM browser_detail_enrichment_queue WHERE id = ?", (queue_id,)
                ).fetchone()
                self.assertEqual("DETAIL_PENDING", recovered["status"])
                self.assertIsNone(recovered["claimed_at"])
                self.assertIsNone(recovered["last_error_code"])
                self.assertEqual(3, recovered["lease_version"])
                self.assertEqual(1, repository.count("browser_detail_attempts"))
                reclaimed = repository.claim_browser_detail(retry_batch)
                self.assertEqual(retry_batch, reclaimed["batch_id"])
                self.assertEqual(3, reclaimed["attempt"])
                self.assertEqual(4, reclaimed["lease_version"])
                with self.assertRaisesRegex(ValueError, "DETAIL_PROCESSING"):
                    repository.fail_browser_detail_queue(
                        queue_id,
                        batch_id=retry_batch,
                        attempt=retry["attempt"],
                        lease_version=retry["lease_version"],
                        attempted_at="2026-08-16T02:05:00Z",
                        extractor_version="detail-extractor-v1",
                        failure_type="TIMEOUT",
                        failure_reason="TIME_LIMIT_EXCEEDED",
                        error_code="PAGE_TIMEOUT",
                    )
                self.assertEqual(
                    [], repository.connection.execute("PRAGMA foreign_key_check").fetchall()
                )

    def test_invalid_transitions_and_migration_16_idempotency_and_rollback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "migration.sqlite3"
            with Repository(path) as repository:
                saved = repository.add_browser_observation(observation(view_count=1))
                with self.assertRaisesRegex(ValueError, "not awaiting"):
                    repository.enqueue_browser_detail(saved["post_url"])
                with self.assertRaisesRegex(ValueError, "DETAIL_PROCESSING"):
                    repository.fail_browser_detail_queue(
                        999,
                        batch_id=999,
                        attempt=1,
                        lease_version=1,
                        attempted_at="2026-08-16T03:00:00Z",
                        extractor_version="detail-extractor-v1",
                        failure_type="TIMEOUT",
                        failure_reason="TIME_LIMIT_EXCEEDED",
                        error_code="PAGE_TIMEOUT",
                    )
            downgrade_before_migration_16(path)
            with Repository(path) as repository:
                digest = repository.connection.execute(
                    "SELECT migration_sha256 FROM schema_migrations WHERE version = 16"
                ).fetchone()[0]
                self.assertEqual(
                    hashlib.sha256(
                        b"16:durable-browser-detail-enrichment-queue-v1"
                    ).hexdigest(),
                    digest,
                )
            with Repository(path) as repository:
                self.assertEqual(
                    1,
                    repository.connection.execute(
                        "SELECT COUNT(*) FROM schema_migrations WHERE version = 16"
                    ).fetchone()[0],
                )

            conflict = Path(directory) / "conflict.sqlite3"
            with Repository(conflict):
                pass
            downgrade_before_migration_16(conflict)
            connection = sqlite3.connect(conflict)
            connection.execute(
                "CREATE TABLE browser_detail_enrichment_queue (id INTEGER PRIMARY KEY)"
            )
            connection.commit()
            connection.close()
            with self.assertRaises(sqlite3.OperationalError):
                Repository(conflict)
            connection = sqlite3.connect(conflict)
            self.assertEqual(
                0,
                connection.execute(
                    "SELECT COUNT(*) FROM schema_migrations WHERE version = 16"
                ).fetchone()[0],
            )
            connection.close()


if __name__ == "__main__":
    unittest.main()
