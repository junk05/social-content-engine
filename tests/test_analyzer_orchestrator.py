import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any, Dict, Mapping

from social_content_engine.analyzer.adapter import AnalysisContext
from social_content_engine.analyzer.cli import main
from social_content_engine.analyzer.mock_adapter import DeterministicMockAdapter
from social_content_engine.analyzer.orchestrator import analyze_post
from social_content_engine.analyzer.validation import AnalyzerOutputError
from social_content_engine.data.repository import Repository


def normalized_post() -> dict:
    return {
        "source": "threads",
        "source_post_id": "post-1",
        "author_id": None,
        "username": "fixture",
        "text": "私は不安？ #相談",
        "permalink": None,
        "published_at": None,
        "media_type": "TEXT_POST",
        "raw_sha256": "0" * 64,
        "normalized_at": "2026-08-16T00:00:00+00:00",
    }


class InvalidAdapter:
    def analyze(
        self, analyzer_input: Mapping[str, Any], context: AnalysisContext
    ) -> Dict[str, Any]:
        return {"not": "an analyzer output"}


class AnalyzerOrchestratorTest(unittest.TestCase):
    def test_reuses_identical_success_and_force_creates_history(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with Repository(Path(directory) / "test.sqlite3") as repository:
                repository.upsert_normalized_post(normalized_post())
                ids = iter(("run-1", "run-2"))
                kwargs = {
                    "now": lambda: "2026-08-16T00:01:00+00:00",
                    "new_run_id": lambda: next(ids),
                }
                first = analyze_post(repository, "post-1", DeterministicMockAdapter(), **kwargs)
                replay = analyze_post(repository, "post-1", DeterministicMockAdapter(), **kwargs)
                forced = analyze_post(
                    repository, "post-1", DeterministicMockAdapter(), force=True, **kwargs
                )
                self.assertFalse(first.reused)
                self.assertTrue(replay.reused)
                self.assertEqual("run-1", replay.analysis_run_id)
                self.assertEqual("run-2", forced.analysis_run_id)
                self.assertEqual(2, repository.count("analysis_runs"))
                self.assertEqual(2, repository.count("post_analysis"))

    def test_invalid_candidate_records_failed_run_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with Repository(Path(directory) / "test.sqlite3") as repository:
                repository.upsert_normalized_post(normalized_post())
                with self.assertRaises(AnalyzerOutputError):
                    analyze_post(
                        repository,
                        "post-1",
                        InvalidAdapter(),
                        now=lambda: "2026-08-16T00:01:00+00:00",
                        new_run_id=lambda: "failed-run",
                    )
                row = repository.connection.execute(
                    "SELECT status, error_code FROM analysis_runs"
                ).fetchone()
                self.assertEqual(("FAILED", "INVALID_SCHEMA"), tuple(row))
                self.assertEqual(0, repository.count("post_analysis"))

    def test_cli_runs_locally_and_reports_replay(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "test.sqlite3"
            with Repository(database) as repository:
                repository.upsert_normalized_post(normalized_post())
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = main(["--database", str(database), "--post-id", "post-1", "--mock"])
            result = json.loads(output.getvalue())
            self.assertEqual(0, exit_code)
            self.assertFalse(result["reused"])
            self.assertEqual("post-1", result["payload"]["source_post_id"])


if __name__ == "__main__":
    unittest.main()
