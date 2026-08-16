import json
import sqlite3
import unittest

from social_content_engine.intelligence.structural import (
    extract_structural_feature,
    materialize_structural_patterns,
)


class _PatternRepository:
    def __init__(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(
            """CREATE TABLE normalized_post_versions (
              id INTEGER PRIMARY KEY, normalized_post_id INTEGER NOT NULL
            );
            CREATE TABLE structural_feature_instances (
              id INTEGER PRIMARY KEY, structural_feature_run_id INTEGER NOT NULL,
              normalized_post_version_id INTEGER NOT NULL, feature_json TEXT NOT NULL,
              input_sha256 TEXT NOT NULL
            );
            CREATE TABLE structural_patterns (
              id INTEGER PRIMARY KEY, structural_feature_run_id INTEGER NOT NULL,
              pattern_kind TEXT NOT NULL, signature_json TEXT NOT NULL,
              signature_sha256 TEXT NOT NULL, input_sha256 TEXT NOT NULL,
              member_count INTEGER NOT NULL, distinct_source_count INTEGER NOT NULL,
              confidence TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE structural_pattern_members (
              structural_pattern_id INTEGER NOT NULL,
              structural_feature_instance_id INTEGER NOT NULL, ordinal INTEGER NOT NULL
            );"""
        )


class StructuralExtractionTest(unittest.TestCase):
    def test_extracts_ordered_components_with_hash_only_evidence(self) -> None:
        feature = extract_structural_feature(
            "女性へ、なぜ今すぐ3つの理由を知るべき？\nまず失敗を避けよう。"
        )
        components = [item["component_id"] for item in feature["components"]]
        for expected in (
            "ASSERTION", "TARGET_READER", "QUESTION", "NUMBER", "LIST_PREVIEW",
            "REASON_PREVIEW", "ADVICE_OR_COMMAND", "TRANSITION",
        ):
            self.assertIn(expected, components)
        self.assertEqual("OBSERVED", feature["first_line_availability"])
        self.assertNotIn("text", feature)
        self.assertIn("text_sha256", str(feature))

    def test_date_metadata_is_unavailable_not_a_post_component(self) -> None:
        feature = extract_structural_feature("2026/08/16")
        self.assertEqual("UNAVAILABLE", feature["first_line_availability"])
        self.assertEqual([], feature["components"])

    def test_promotes_only_repeated_non_generic_text_free_patterns(self) -> None:
        repository = _PatternRepository()
        first = extract_structural_feature("女性へ、なぜ？")
        second = extract_structural_feature("男性へ、なぜ？")
        generic = extract_structural_feature("短文")
        repository.connection.executemany(
            "INSERT INTO normalized_post_versions VALUES (?, ?)", [(1, 10), (2, 11), (3, 12)]
        )
        repository.connection.executemany(
            """INSERT INTO structural_feature_instances
            (id, structural_feature_run_id, normalized_post_version_id, feature_json, input_sha256)
            VALUES (?, 1, ?, ?, ?)""",
            [
                (1, 1, json.dumps(first, sort_keys=True), "a" * 64),
                (2, 2, json.dumps(second, sort_keys=True), "b" * 64),
                (3, 3, json.dumps(generic, sort_keys=True), "c" * 64),
            ],
        )
        self.assertGreaterEqual(materialize_structural_patterns(repository, 1), 1)
        rows = repository.connection.execute(
            "SELECT pattern_kind, signature_json FROM structural_patterns ORDER BY pattern_kind"
        ).fetchall()
        self.assertTrue(any(row["pattern_kind"] == "FIRST_LINE" for row in rows))
        self.assertNotIn("女性", "".join(str(row["signature_json"]) for row in rows))


if __name__ == "__main__":
    unittest.main()
