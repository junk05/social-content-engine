import copy
import unittest

from social_content_engine.analyzer.adapter import AnalysisContext
from social_content_engine.analyzer.mock_adapter import DeterministicMockAdapter
from social_content_engine.analyzer.preprocessing import build_analyzer_input, input_sha256
from social_content_engine.analyzer.validation import AnalyzerOutputError, validate_analyzer_output


class AnalyzerValidationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.analyzer_input = build_analyzer_input(
            {"source": "threads", "source_post_id": "post-1", "text": "私は不安？ #相談"}
        )
        self.context = AnalysisContext(
            "run-1",
            "mock-v1",
            "M1_TAXONOMY_V1",
            "prompt-v1",
            "deterministic",
            "mock",
            {},
            input_sha256(self.analyzer_input),
            "2026-08-16T00:00:00+00:00",
        )
        self.valid = DeterministicMockAdapter().analyze(self.analyzer_input, self.context)

    def assert_rejected(self, candidate: dict, code: str) -> None:
        with self.assertRaises(AnalyzerOutputError) as raised:
            validate_analyzer_output(candidate, self.analyzer_input, self.context)
        self.assertEqual(code, raised.exception.code)

    def test_accepts_exact_unicode_spans_and_supported_content(self) -> None:
        self.valid["content"]["primary_topic"] = "悩み相談"
        validate_analyzer_output(self.valid, self.analyzer_input, self.context)

    def test_rejects_out_of_bounds_and_non_matching_quotes(self) -> None:
        outside = copy.deepcopy(self.valid)
        outside["actions"][0]["evidence"][0]["end"] = 999
        self.assert_rejected(outside, "INVALID_EVIDENCE_SPAN")

        mismatch = copy.deepcopy(self.valid)
        mismatch["actions"][0]["evidence"][0]["quote"] = "別の文字"
        self.assert_rejected(mismatch, "EVIDENCE_QUOTE_MISMATCH")

    def test_rejects_invalid_schema_before_semantics(self) -> None:
        candidate = copy.deepcopy(self.valid)
        candidate["actions"][0]["label"] = "DIAGNOSE"
        self.assert_rejected(candidate, "INVALID_SCHEMA")

    def test_rejects_context_metadata_substitution(self) -> None:
        candidate = copy.deepcopy(self.valid)
        candidate["analysis_run_id"] = "other-run"
        self.assert_rejected(candidate, "METADATA_MISMATCH")

    def test_rejects_invented_content_and_entity(self) -> None:
        for field in ("keywords", "entities"):
            candidate = copy.deepcopy(self.valid)
            candidate["content"][field].append("本文にない人物")
            with self.subTest(field=field):
                self.assert_rejected(candidate, "UNSUPPORTED_CONTENT")


if __name__ == "__main__":
    unittest.main()
