import sqlite3
import tempfile
import unittest
from pathlib import Path

from social_content_engine.data.repository import Repository


def normalized_post() -> dict:
    return {
        "source": "threads",
        "source_post_id": "post-1",
        "author_id": None,
        "username": "fixture",
        "text": "質問ですか？",
        "permalink": None,
        "published_at": None,
        "media_type": "TEXT_POST",
        "raw_sha256": "0" * 64,
        "normalized_at": "2026-08-16T00:00:00+00:00",
    }


def run_metadata(run_id: str) -> dict:
    return {
        "analysis_run_id": run_id,
        "source": "threads",
        "source_post_id": "post-1",
        "normalized_post_version": 1,
        "analyzer_version": "mock-v1",
        "taxonomy_version": "M1_TAXONOMY_V1",
        "prompt_version": "prompt-v1",
        "model_provider": "deterministic",
        "model_name": "mock",
        "model_parameters": {},
        "input_sha256": "1" * 64,
        "analyzed_at": "2026-08-16T00:01:00+00:00",
    }


class AnalysisRepositoryTest(unittest.TestCase):
    def test_persists_append_only_analysis_history(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with Repository(Path(directory) / "test.sqlite3") as repository:
                repository.upsert_normalized_post(normalized_post())
                first = repository.start_analysis_run(run_metadata("run-1"))
                repository.persist_analysis(first, "post-1", {"run": 1}, "a" * 64)
                second = repository.start_analysis_run(run_metadata("run-2"))
                repository.persist_analysis(second, "post-1", {"run": 2}, "b" * 64)

                self.assertEqual(2, repository.count("analysis_runs"))
                self.assertEqual(2, repository.count("post_analysis"))
                rows = repository.connection.execute(
                    "SELECT status, output_sha256 FROM analysis_runs ORDER BY id"
                ).fetchall()
                self.assertEqual(["SUCCEEDED", "SUCCEEDED"], [row["status"] for row in rows])
                self.assertEqual(["a" * 64, "b" * 64], [row["output_sha256"] for row in rows])

    def test_records_failed_attempt_without_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with Repository(Path(directory) / "test.sqlite3") as repository:
                repository.upsert_normalized_post(normalized_post())
                row_id = repository.start_analysis_run(run_metadata("failed-run"))
                repository.fail_analysis_run(row_id, "INVALID_OUTPUT")
                row = repository.connection.execute(
                    "SELECT status, error_code FROM analysis_runs WHERE id = ?", (row_id,)
                ).fetchone()
                self.assertEqual("FAILED", row["status"])
                self.assertEqual("INVALID_OUTPUT", row["error_code"])
                self.assertEqual(0, repository.count("post_analysis"))
                with self.assertRaises(ValueError):
                    repository.persist_analysis(row_id, "post-1", {}, "c" * 64)

    def test_migrates_empty_reserved_m0_tables_without_touching_posts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.sqlite3"
            connection = sqlite3.connect(path)
            connection.executescript(
                """
                CREATE TABLE analysis_runs (
                  id INTEGER PRIMARY KEY, analyzer_version TEXT NOT NULL,
                  taxonomy_version TEXT NOT NULL, model TEXT NOT NULL,
                  prompt_version TEXT NOT NULL, analyzed_at TEXT NOT NULL
                );
                CREATE TABLE post_analysis (
                  id INTEGER PRIMARY KEY, analysis_run_id INTEGER NOT NULL,
                  source_post_id TEXT NOT NULL, payload_json TEXT NOT NULL
                );
                """
            )
            connection.close()
            with Repository(path) as repository:
                repository.upsert_normalized_post(normalized_post())
                self.assertEqual("質問ですか？", repository.get_normalized_post("post-1")["text"])
                columns = {
                    row["name"]
                    for row in repository.connection.execute(
                        "PRAGMA table_info(analysis_runs)"
                    ).fetchall()
                }
                self.assertIn("analysis_run_id", columns)


if __name__ == "__main__":
    unittest.main()
