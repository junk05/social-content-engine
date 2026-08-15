import hashlib
import sqlite3
import tempfile
import unittest
from pathlib import Path

from social_content_engine.data.repository import Repository


def seed_post(repository: Repository) -> tuple:
    body = b'{"data":[{"id":"post-1","text":"fixture"}]}'
    run_id = repository.add_collection_run(
        endpoint="/keyword_search",
        request={"params": {"q": "fixture"}},
        started_at="2026-08-16T00:00:00+00:00",
        completed_at="2026-08-16T00:00:01+00:00",
        http_status=200,
        response_headers={"content-type": "application/json"},
        raw_response=body,
        raw_response_sha256=hashlib.sha256(body).hexdigest(),
        collector_version="test-collector",
    )
    raw_json = b'{"id":"post-1","text":"fixture"}'
    raw_sha = hashlib.sha256(raw_json).hexdigest()
    raw_id = repository.add_raw_post(
        collection_run_id=run_id,
        source_post_id="post-1",
        raw_json=raw_json,
        raw_sha256=raw_sha,
        retrieved_at="2026-08-16T00:00:01+00:00",
    )
    repository.upsert_normalized_post(
        {
            "schema_version": 1,
            "source": "threads",
            "source_post_id": "post-1",
            "author_id": None,
            "username": "fixture",
            "text": "fixture",
            "permalink": None,
            "published_at": None,
            "media_type": "TEXT_POST",
            "raw_sha256": raw_sha,
            "normalized_at": "2026-08-16T00:00:01+00:00",
        },
        source_raw_post_id=raw_id,
    )
    version_id = int(
        repository.connection.execute(
            "SELECT current_version_id FROM normalized_posts WHERE source_post_id = 'post-1'"
        ).fetchone()[0]
    )
    return run_id, raw_id, version_id


class M2RepositoryTest(unittest.TestCase):
    def test_batch_queries_have_deterministic_hashes_order_and_unique_run_link(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with Repository(Path(directory) / "test.sqlite3") as repository:
                run_id, _, _ = seed_post(repository)
                batch_id = repository.create_collection_batch(
                    "batch-1",
                    {"z": 1, "queries": ["alpha", "beta"]},
                    "collector-v2",
                    started_at="2026-08-16T00:00:00+00:00",
                )
                first = repository.add_collection_batch_query(
                    batch_id, 0, {"search_type": "RECENT", "q": "alpha"}
                )
                repository.add_collection_batch_query(
                    batch_id, 1, {"q": "beta", "search_type": "TOP"}
                )
                with self.assertRaises(sqlite3.IntegrityError):
                    repository.add_collection_batch_query(
                        batch_id, 2, {"search_type": "RECENT", "q": "alpha"}
                    )
                repository.link_collection_run(first, run_id)
                with self.assertRaises(sqlite3.IntegrityError):
                    repository.link_collection_run(first, run_id)
                batch = repository.connection.execute(
                    "SELECT config_json, config_sha256 FROM collection_batches"
                ).fetchone()
                self.assertEqual(
                    hashlib.sha256(batch["config_json"].encode("utf-8")).hexdigest(),
                    batch["config_sha256"],
                )
                rows = repository.connection.execute(
                    """SELECT ordinal, query_json, query_sha256
                    FROM collection_batch_queries ORDER BY ordinal"""
                ).fetchall()
                self.assertEqual([0, 1], [row["ordinal"] for row in rows])
                for row in rows:
                    expected = hashlib.sha256(row["query_json"].encode("utf-8")).hexdigest()
                    self.assertEqual(expected, row["query_sha256"])
                repository.complete_collection_batch(
                    batch_id, completed_at="2026-08-16T00:02:00+00:00"
                )
                with self.assertRaises(ValueError):
                    repository.complete_collection_batch(batch_id)
                with self.assertRaises(ValueError):
                    repository.add_collection_batch_query(
                        batch_id, 2, {"q": "gamma", "search_type": "RECENT"}
                    )

    def test_dataset_members_are_unique_and_finalized_snapshot_is_immutable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with Repository(Path(directory) / "test.sqlite3") as repository:
                _, raw_id, version_id = seed_post(repository)
                snapshot_id = repository.create_dataset_snapshot(
                    "dataset-1",
                    1,
                    {"order_by": "source_post_id", "source": "threads"},
                    created_at="2026-08-16T00:03:00+00:00",
                )
                repository.add_dataset_member(
                    snapshot_id, version_id, raw_id, 0, {"rule": "all-collected"}
                )
                with self.assertRaises(sqlite3.IntegrityError):
                    repository.add_dataset_member(
                        snapshot_id, version_id, raw_id, 1, {"rule": "duplicate"}
                    )
                snapshot = repository.connection.execute(
                    "SELECT selection_spec_json, selection_spec_sha256 FROM dataset_snapshots"
                ).fetchone()
                expected = hashlib.sha256(
                    snapshot["selection_spec_json"].encode("utf-8")
                ).hexdigest()
                self.assertEqual(expected, snapshot["selection_spec_sha256"])
                repository.finalize_dataset_snapshot(
                    snapshot_id, finalized_at="2026-08-16T00:04:00+00:00"
                )
                with self.assertRaises(ValueError):
                    repository.add_dataset_member(
                        snapshot_id, version_id, raw_id, 1, {"rule": "late"}
                    )
                with self.assertRaises(ValueError):
                    repository.finalize_dataset_snapshot(snapshot_id)
                with self.assertRaises(sqlite3.IntegrityError):
                    repository.connection.execute(
                        "UPDATE dataset_members SET ordinal = 2 WHERE dataset_snapshot_id = ?",
                        (snapshot_id,),
                    )

    def test_metrics_preserve_zero_and_separate_observations(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with Repository(Path(directory) / "test.sqlite3") as repository:
                run_id, raw_id, _ = seed_post(repository)
                kwargs = {
                    "source": "threads",
                    "source_post_id": "post-1",
                    "metric_name": "reply_count",
                    "metric_value": 0,
                    "observed_at": "2026-08-16T00:05:00+00:00",
                    "api_field": "reply_count",
                    "unit": "count",
                    "collector_version": "collector-v2",
                    "raw_post_id": raw_id,
                    "collection_run_id": run_id,
                }
                repository.add_metric_observation(**kwargs)
                repository.add_metric_observation(**kwargs)
                rows = repository.connection.execute(
                    "SELECT metric_value FROM post_metric_observations ORDER BY id"
                ).fetchall()
                self.assertEqual([0, 0], [row["metric_value"] for row in rows])
                for invalid in (-1, 1.5, True):
                    with self.subTest(invalid=invalid):
                        bad = dict(kwargs)
                        bad["metric_value"] = invalid
                        with self.assertRaises((TypeError, ValueError)):
                            repository.add_metric_observation(**bad)
                missing = dict(kwargs)
                missing["raw_post_id"] = None
                missing["collection_run_id"] = None
                with self.assertRaises(ValueError):
                    repository.add_metric_observation(**missing)

    def test_migration_three_is_idempotent_and_database_is_consistent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.sqlite3"
            with Repository(path):
                pass
            with Repository(path) as repository:
                migration = repository.connection.execute(
                    "SELECT migration_sha256 FROM schema_migrations WHERE version = 3"
                ).fetchone()
                self.assertRegex(migration["migration_sha256"], r"^[0-9a-f]{64}$")
                self.assertEqual([], repository.connection.execute(
                    "PRAGMA foreign_key_check"
                ).fetchall())
                self.assertEqual(
                    "ok", repository.connection.execute("PRAGMA integrity_check").fetchone()[0]
                )


if __name__ == "__main__":
    unittest.main()
