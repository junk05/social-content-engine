import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from social_content_engine.analyzer.mock_adapter import DeterministicMockAdapter
from social_content_engine.analyzer.orchestrator import analyze_post
from social_content_engine.data.repository import Repository
from social_content_engine.intelligence.first_line import (
    build_first_line_feature,
    extract_first_line,
)


def analysis_payload(text: str) -> dict:
    return {
        "actions": [
            {
                "label": "ASK",
                "evidence": [
                    {
                        "quote": "？",
                        "start": text.index("？"),
                        "end": text.index("？") + 1,
                    }
                ],
            }
        ]
        if "？" in text
        else [],
        "structures": [
            {
                "label": "SHORT_PUNCHY",
                "evidence": [{"quote": text, "start": 0, "end": len(text)}],
            }
        ]
        if text
        else [],
    }


def add_post(repository: Repository, text: str) -> int:
    repository.upsert_normalized_post(
        {
            "schema_version": 1,
            "source": "threads",
            "source_post_id": "post-1",
            "author_id": None,
            "username": "fixture",
            "text": text,
            "permalink": None,
            "published_at": None,
            "media_type": "TEXT_POST",
            "raw_sha256": "0" * 64,
            "normalized_at": "2026-08-16T00:00:00+00:00",
        }
    )
    result = analyze_post(
        repository,
        "post-1",
        DeterministicMockAdapter(),
        now=lambda: "2026-08-16T00:01:00+00:00",
        new_run_id=lambda: "run-1",
    )
    return result.analysis_run_row_id


class FirstLineTest(unittest.TestCase):
    def test_blank_crlf_nfc_span_hash_and_overlapping_labels(self) -> None:
        normalized = "\r\n  Caféで、なぜ？  \r\nsecond"
        feature = build_first_line_feature(normalized, analysis_payload(normalized))
        line = "Caféで、なぜ？"
        self.assertEqual("OBSERVED", feature["availability"])
        self.assertEqual(line, normalized[feature["start"] : feature["end"]])
        self.assertEqual(hashlib.sha256(line.encode("utf-8")).hexdigest(), feature["text_sha256"])
        self.assertEqual(len(line), feature["char_count"])
        self.assertEqual("QUESTION", feature["terminal_mark"])
        self.assertEqual("QUESTION", feature["hook_family"])
        self.assertEqual("WHY_QUESTION", feature["hook_subtype"])
        self.assertEqual(3, feature["curiosity_gap"])
        self.assertEqual("ANSWER", feature["expected_action"])
        self.assertEqual(["ASK"], feature["m1_action_labels"])
        self.assertEqual(["SHORT_PUNCHY"], feature["m1_structure_labels"])
        self.assertNotIn("text", feature)

    def test_japanese_contrarian_and_emoji_markers_are_explicit(self) -> None:
        contrarian = build_first_line_feature(
            "でも、常識は間違い！", {"actions": [], "structures": []}
        )
        self.assertEqual("CONTRARIAN", contrarian["hook_family"])
        self.assertEqual(3, contrarian["contrarian_level"])
        self.assertEqual(2, contrarian["emotional_intensity"])
        emoji = build_first_line_feature("うれしい😊", {"actions": [], "structures": []})
        self.assertEqual("OTHER", emoji["terminal_mark"])
        self.assertEqual(1, emoji["emotional_intensity"])

    def test_empty_uses_unknown_scores_without_inference(self) -> None:
        feature = build_first_line_feature(" \r\n\t", {"actions": [], "structures": []})
        self.assertEqual("EMPTY", feature["availability"])
        for key in (
            "curiosity_gap",
            "self_relevance",
            "target_specificity",
            "emotional_intensity",
            "contrarian_level",
            "read_more_pressure",
        ):
            self.assertEqual("UNKNOWN", feature[key])
        self.assertIsNone(feature["text_sha256"])

    def test_persistence_replays_and_never_stores_source_text(self) -> None:
        source_text = "あなたへ：なぜ？"
        with tempfile.TemporaryDirectory() as directory:
            with Repository(Path(directory) / "test.sqlite3") as repository:
                row_id = add_post(repository, source_text)
                first = extract_first_line(
                    repository,
                    row_id,
                    extracted_at=lambda: "2026-08-16T00:02:00+00:00",
                )
                replay = extract_first_line(
                    repository,
                    row_id,
                    extracted_at=lambda: "2026-08-16T00:03:00+00:00",
                )
                self.assertFalse(first["reused"])
                self.assertTrue(replay["reused"])
                self.assertEqual(first["feature_sha256"], replay["feature_sha256"])
                row = repository.connection.execute(
                    "SELECT feature_json FROM first_line_features"
                ).fetchone()
                self.assertNotIn(source_text, row["feature_json"])
                self.assertNotIn('"text"', row["feature_json"])
                self.assertEqual(1, repository.count("first_line_features"))
                migration = repository.connection.execute(
                    "SELECT migration_sha256 FROM schema_migrations WHERE version = 5"
                ).fetchone()
                self.assertRegex(migration["migration_sha256"], r"^[0-9a-f]{64}$")

    def test_repository_rejects_text_or_quote_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with Repository(Path(directory) / "test.sqlite3") as repository:
                row_id = add_post(repository, "質問？")
                source = repository.get_analysis_feature_source(row_id)
                for leaked in ({"text": "質問？"}, {"nested": {"quote": "質問？"}}):
                    with self.subTest(leaked=leaked):
                        with self.assertRaisesRegex(ValueError, "source text"):
                            repository.persist_first_line_feature(
                                analysis_run_row_id=row_id,
                                normalized_post_version_id=int(
                                    source["normalized_post_version_id"]
                                ),
                                extractor_version="negative-" + hashlib.sha256(
                                    json.dumps(leaked).encode("utf-8")
                                ).hexdigest(),
                                feature_contract_version="M2_FIRST_LINE_V1",
                                input_sha256=str(source["input_sha256"]),
                                feature=leaked,
                                extracted_at="2026-08-16T00:02:00+00:00",
                            )


if __name__ == "__main__":
    unittest.main()
