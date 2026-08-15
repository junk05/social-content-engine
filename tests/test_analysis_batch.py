import hashlib
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, Mapping

from social_content_engine.analyzer.adapter import AnalysisContext
from social_content_engine.analyzer.batch import run_analysis_batch
from social_content_engine.analyzer.mock_adapter import DeterministicMockAdapter
from social_content_engine.analyzer.orchestrator import analyze_normalized_version
from social_content_engine.data.repository import Repository

CONFIG = {
    "analyzer_version": "m1-analyzer-v1",
    "taxonomy_version": "M1_TAXONOMY_V1",
    "prompt_version": "m1-mock-prompt-v1",
    "model_provider": "deterministic",
    "model_name": "mock",
    "model_parameters": {},
}


def add_post(repository: Repository, post_id: str, text: str, ordinal: int) -> tuple:
    body = ('{"id":"' + post_id + '","text":"' + text + '"}').encode("utf-8")
    run_id = repository.add_collection_run(
        endpoint="/fixture",
        request={"ordinal": ordinal},
        started_at="2026-08-16T00:00:00+00:00",
        completed_at="2026-08-16T00:00:01+00:00",
        http_status=200,
        response_headers={},
        raw_response=body,
        raw_response_sha256=hashlib.sha256(body).hexdigest(),
        collector_version="test",
    )
    raw_id = repository.add_raw_post(
        collection_run_id=run_id,
        source_post_id=post_id,
        raw_json=body,
        raw_sha256=hashlib.sha256(body).hexdigest(),
        retrieved_at="2026-08-16T00:00:01+00:00",
    )
    repository.upsert_normalized_post(
        {
            "schema_version": 1,
            "source": "threads",
            "source_post_id": post_id,
            "author_id": None,
            "username": "fixture",
            "text": text,
            "permalink": None,
            "published_at": None,
            "media_type": "TEXT_POST",
            "raw_sha256": hashlib.sha256(body).hexdigest(),
            "normalized_at": "2026-08-16T00:00:01+00:00",
        },
        source_raw_post_id=raw_id,
    )
    version_id = int(
        repository.connection.execute(
            "SELECT current_version_id FROM normalized_posts WHERE source_post_id = ?",
            (post_id,),
        ).fetchone()[0]
    )
    return raw_id, version_id


def snapshot(repository: Repository, finalized: bool = True) -> int:
    snapshot_id = repository.create_dataset_snapshot("fixture", 1, {"all": True})
    posts = (("post-1", "質問？"), ("post-2", "私は参加しました"))
    for ordinal, (post_id, text) in enumerate(posts):
        raw_id, version_id = add_post(repository, post_id, text, ordinal)
        repository.add_dataset_member(snapshot_id, version_id, raw_id, ordinal, {"all": True})
    if finalized:
        repository.finalize_dataset_snapshot(snapshot_id)
    return snapshot_id


class FailPostTwoOnce:
    def __init__(self) -> None:
        self.failed = False
        self.delegate = DeterministicMockAdapter()

    def analyze(
        self, analyzer_input: Mapping[str, Any], context: AnalysisContext
    ) -> Dict[str, Any]:
        if analyzer_input["source_post_id"] == "post-2" and not self.failed:
            self.failed = True
            raise RuntimeError("injected failure")
        return self.delegate.analyze(analyzer_input, context)


class AnalysisBatchTest(unittest.TestCase):
    def test_requires_finalized_dataset_and_analyzes_two_items(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with Repository(Path(directory) / "test.sqlite3") as repository:
                draft = snapshot(repository, finalized=False)
                with self.assertRaisesRegex(ValueError, "finalized"):
                    repository.create_analysis_batch("draft", draft, CONFIG)
                repository.finalize_dataset_snapshot(draft)
                batch_id = repository.create_analysis_batch("batch-1", draft, CONFIG)
                batch = repository.connection.execute(
                    "SELECT config_sha256 FROM analysis_batches WHERE id = ?", (batch_id,)
                ).fetchone()
                self.assertRegex(batch["config_sha256"], r"^[0-9a-f]{64}$")
                migration = repository.connection.execute(
                    "SELECT migration_sha256 FROM schema_migrations WHERE version = 4"
                ).fetchone()
                self.assertRegex(migration["migration_sha256"], r"^[0-9a-f]{64}$")
                result = run_analysis_batch(repository, batch_id, DeterministicMockAdapter())
                self.assertEqual((2, 0, 0), (result.succeeded, result.failed, result.skipped))
                self.assertEqual("SUCCEEDED", result.status)
                self.assertEqual(2, repository.count("post_analysis"))

    def test_restart_skips_success_and_retries_failure_with_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with Repository(Path(directory) / "test.sqlite3") as repository:
                batch_id = repository.create_analysis_batch("batch-1", snapshot(repository), CONFIG)
                adapter = FailPostTwoOnce()
                first = run_analysis_batch(repository, batch_id, adapter)
                self.assertEqual((1, 1), (first.succeeded, first.failed))
                self.assertEqual("PARTIAL_FAILED", first.status)
                second = run_analysis_batch(repository, batch_id, adapter)
                self.assertEqual((1, 0, 1), (second.succeeded, second.failed, second.skipped))
                rows = repository.connection.execute(
                    """SELECT status, attempt, analysis_run_row_id
                    FROM analysis_batch_items ORDER BY id"""
                ).fetchall()
                self.assertEqual(["SUCCEEDED", "SUCCEEDED"], [row["status"] for row in rows])
                self.assertEqual([1, 2], [row["attempt"] for row in rows])
                self.assertTrue(all(row["analysis_run_row_id"] is not None for row in rows))
                self.assertEqual(3, repository.count("analysis_runs"))

    def test_batch_links_historical_version_not_current_post(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with Repository(Path(directory) / "test.sqlite3") as repository:
                snapshot_id = snapshot(repository)
                pinned = int(
                    repository.connection.execute(
                        """SELECT normalized_post_version_id FROM dataset_members
                        WHERE dataset_snapshot_id = ? ORDER BY ordinal LIMIT 1""",
                        (snapshot_id,),
                    ).fetchone()[0]
                )
                add_post(repository, "post-1", "changed current text", 99)
                batch_id = repository.create_analysis_batch("batch-1", snapshot_id, CONFIG)
                run_analysis_batch(repository, batch_id, DeterministicMockAdapter())
                linked = int(
                    repository.connection.execute(
                        """SELECT analysis_runs.normalized_post_version_id
                        FROM analysis_batch_items JOIN analysis_runs
                          ON analysis_runs.id = analysis_batch_items.analysis_run_row_id
                        WHERE analysis_batch_items.normalized_post_version_id = ?""",
                        (pinned,),
                    ).fetchone()[0]
                )
                self.assertEqual(pinned, linked)

    def test_reuse_identity_separates_provider_and_normalized_version(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with Repository(Path(directory) / "test.sqlite3") as repository:
                _, version_one = add_post(repository, "post-1", "質問？", 0)
                first = analyze_normalized_version(
                    repository,
                    version_one,
                    DeterministicMockAdapter(),
                    model_provider="provider-a",
                    new_run_id=lambda: "run-a",
                )
                other_provider = analyze_normalized_version(
                    repository,
                    version_one,
                    DeterministicMockAdapter(),
                    model_provider="provider-b",
                    new_run_id=lambda: "run-b",
                )
                _, version_two = add_post(repository, "post-1", "質問？ changed", 1)
                other_version = analyze_normalized_version(
                    repository,
                    version_two,
                    DeterministicMockAdapter(),
                    model_provider="provider-a",
                    new_run_id=lambda: "run-v2",
                )
                self.assertFalse(first.reused)
                self.assertFalse(other_provider.reused)
                self.assertFalse(other_version.reused)
                self.assertEqual(3, repository.count("analysis_runs"))

    def test_restart_recovers_item_left_running_by_interruption(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with Repository(Path(directory) / "test.sqlite3") as repository:
                batch_id = repository.create_analysis_batch("batch-1", snapshot(repository), CONFIG)
                item = repository.pending_analysis_batch_items(batch_id)[0]
                repository.start_analysis_batch_item(
                    int(item["id"]), started_at="2026-08-16T00:10:00+00:00"
                )
                result = run_analysis_batch(repository, batch_id, DeterministicMockAdapter())
                self.assertEqual(2, result.succeeded)
                recovered = repository.connection.execute(
                    "SELECT status, attempt FROM analysis_batch_items WHERE id = ?",
                    (item["id"],),
                ).fetchone()
                self.assertEqual(("SUCCEEDED", 2), tuple(recovered))


if __name__ == "__main__":
    unittest.main()
