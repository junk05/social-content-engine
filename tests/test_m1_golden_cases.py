import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from social_content_engine.analyzer.adapter import AnalysisContext
from social_content_engine.analyzer.mock_adapter import DeterministicMockAdapter
from social_content_engine.analyzer.orchestrator import analyze_post
from social_content_engine.analyzer.preprocessing import (
    build_analyzer_input,
    canonical_json_bytes,
    input_sha256,
)
from social_content_engine.analyzer.validation import validate_analyzer_output
from social_content_engine.data.repository import Repository

FIXTURE = Path(__file__).parent / "fixtures" / "m1_golden_cases.json"


def normalized_post(post_id: str, text: str) -> dict:
    return {
        "source": "threads",
        "source_post_id": post_id,
        "author_id": None,
        "username": "sanitized-fixture",
        "text": text,
        "permalink": None,
        "published_at": None,
        "media_type": "TEXT_POST",
        "raw_sha256": "0" * 64,
        "normalized_at": "2026-08-16T00:00:00+00:00",
    }


class M1GoldenCasesTest(unittest.TestCase):
    def test_golden_cases_freeze_bounded_structural_behavior(self) -> None:
        cases = json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]
        for case in cases:
            with self.subTest(case=case["id"]):
                analyzer_input = build_analyzer_input(
                    normalized_post(case["id"], case["text"])
                )
                context = AnalysisContext(
                    "golden-" + case["id"],
                    "mock-v1",
                    "M1_TAXONOMY_V1",
                    "prompt-v1",
                    "deterministic",
                    "mock",
                    {},
                    input_sha256(analyzer_input),
                    "2026-08-16T00:01:00+00:00",
                )
                candidate = DeterministicMockAdapter().analyze(analyzer_input, context)
                validate_analyzer_output(candidate, analyzer_input, context)
                self.assertEqual(
                    case["expected_actions"], [item["label"] for item in candidate["actions"]]
                )
                self.assertEqual(
                    case["expected_structures"],
                    [item["label"] for item in candidate["structures"]],
                )
                self.assertEqual(
                    case["expected_psychology"],
                    [item["label"] for item in candidate["psychology_hypotheses"]],
                )
                if "expected_normalized_text" in case:
                    self.assertEqual(case["expected_normalized_text"], analyzer_input["text"])
                for name, expected in case.get("expected_features", {}).items():
                    self.assertEqual(expected, analyzer_input["text_features"][name])

    def test_replay_hash_and_security_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with Repository(Path(directory) / "test.sqlite3") as repository:
                repository.upsert_normalized_post(
                    normalized_post("security-case", "私は不安？ #相談")
                )
                first = analyze_post(
                    repository,
                    "security-case",
                    DeterministicMockAdapter(),
                    now=lambda: "2026-08-16T00:01:00+00:00",
                    new_run_id=lambda: "golden-run",
                )
                replay = analyze_post(
                    repository, "security-case", DeterministicMockAdapter()
                )
                self.assertTrue(replay.reused)
                self.assertEqual(first.analysis_run_id, replay.analysis_run_id)
                row = repository.connection.execute(
                    """SELECT analysis_runs.output_sha256, analysis_runs.model_parameters_json,
                              post_analysis.payload_json
                       FROM analysis_runs JOIN post_analysis
                         ON post_analysis.analysis_run_row_id = analysis_runs.id"""
                ).fetchone()
                expected_hash = hashlib.sha256(canonical_json_bytes(first.payload)).hexdigest()
                self.assertEqual(expected_hash, row["output_sha256"])
                persisted = row["model_parameters_json"] + row["payload_json"]
                for forbidden in ("access_token", "api_key", "client_secret"):
                    self.assertNotIn(forbidden, persisted.casefold())


if __name__ == "__main__":
    unittest.main()
