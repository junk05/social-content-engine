import copy
import unittest

import jsonschema

from social_content_engine.analyzer.contracts import validate_output_contract


def valid_output() -> dict:
    return {
        "schema_version": 1,
        "analysis_run_id": "run-1",
        "source_post_id": "post-1",
        "taxonomy_version": "M1_TAXONOMY_V1",
        "analyzer_version": "mock-v1",
        "prompt_version": "prompt-v1",
        "model": {"provider": "deterministic", "name": "mock", "parameters": {}},
        "input_sha256": "0" * 64,
        "actions": [
            {
                "label": "ASK",
                "confidence": "HIGH",
                "evidence": [{"quote": "どう？", "start": 0, "end": 3}],
            }
        ],
        "psychology_hypotheses": [
            {
                "label": "UNCERTAINTY",
                "confidence": "LOW",
                "evidence": [{"quote": "どう？", "start": 0, "end": 3}],
                "inference": True,
            }
        ],
        "structures": [
            {
                "label": "QUESTION_LED",
                "confidence": "HIGH",
                "evidence": [{"quote": "どう？", "start": 0, "end": 3}],
            }
        ],
        "content": {
            "primary_topic": "質問",
            "secondary_topics": [],
            "entities": [],
            "keywords": ["どう"],
        },
        "warnings": [],
        "analyzed_at": "2026-08-16T00:00:00+00:00",
    }


class AnalyzerContractTest(unittest.TestCase):
    def test_accepts_valid_closed_taxonomy_output(self) -> None:
        validate_output_contract(valid_output())

    def test_rejects_unknown_label_and_confidence(self) -> None:
        for field, value in (("label", "DIAGNOSE"), ("confidence", "CERTAIN")):
            candidate = copy.deepcopy(valid_output())
            candidate["actions"][0][field] = value
            with self.subTest(field=field), self.assertRaises(jsonschema.ValidationError):
                validate_output_contract(candidate)

    def test_rejects_psychology_without_explicit_inference(self) -> None:
        candidate = copy.deepcopy(valid_output())
        del candidate["psychology_hypotheses"][0]["inference"]
        with self.assertRaises(jsonschema.ValidationError):
            validate_output_contract(candidate)

    def test_rejects_extra_or_invalid_version_metadata(self) -> None:
        candidate = copy.deepcopy(valid_output())
        candidate["taxonomy_version"] = "future"
        candidate["secret"] = "must not be accepted"
        with self.assertRaises(jsonschema.ValidationError):
            validate_output_contract(candidate)


if __name__ == "__main__":
    unittest.main()
