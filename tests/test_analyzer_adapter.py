import copy
import unittest

from social_content_engine.analyzer.adapter import AnalysisContext, AnalyzerAdapter
from social_content_engine.analyzer.contracts import validate_output_contract
from social_content_engine.analyzer.mock_adapter import DeterministicMockAdapter
from social_content_engine.analyzer.preprocessing import build_analyzer_input, input_sha256


class AnalyzerAdapterTest(unittest.TestCase):
    def test_mock_implements_boundary_and_is_deterministic(self) -> None:
        analyzer_input = build_analyzer_input(
            {
                "source": "threads",
                "source_post_id": "post-1",
                "text": "私は不安。どうすればいい？ #相談",
            }
        )
        context = AnalysisContext(
            analysis_run_id="run-1",
            analyzer_version="mock-v1",
            taxonomy_version="M1_TAXONOMY_V1",
            prompt_version="prompt-v1",
            model_provider="deterministic",
            model_name="mock",
            model_parameters={},
            input_sha256=input_sha256(analyzer_input),
            analyzed_at="2026-08-16T00:00:00+00:00",
        )
        adapter: AnalyzerAdapter = DeterministicMockAdapter()
        first = adapter.analyze(analyzer_input, context)
        second = adapter.analyze(copy.deepcopy(analyzer_input), context)

        self.assertEqual(first, second)
        self.assertEqual(["ASK", "SHARE_EXPERIENCE", "EXPRESS_EMOTION"], [
            item["label"] for item in first["actions"]
        ])
        self.assertEqual("FEAR_OR_ANXIETY_EXPRESSED", first["psychology_hypotheses"][0]["label"])
        validate_output_contract(first)

    def test_ambiguous_text_omits_psychology(self) -> None:
        analyzer_input = build_analyzer_input(
            {"source": "threads", "source_post_id": "post-2", "text": "今日の記録"}
        )
        context = AnalysisContext(
            "run-2", "mock-v1", "M1_TAXONOMY_V1", "prompt-v1",
            "deterministic", "mock", {}, input_sha256(analyzer_input),
            "2026-08-16T00:00:00+00:00",
        )
        result = DeterministicMockAdapter().analyze(analyzer_input, context)
        self.assertEqual([], result["psychology_hypotheses"])
        validate_output_contract(result)


if __name__ == "__main__":
    unittest.main()
