import json
import sqlite3
import unittest

from social_content_engine.intelligence.m4_intelligence import (
    build_intelligence_feature,
    materialize_sequence_patterns,
    sequence_signature,
)


class _SequenceRepository:
    def __init__(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(
            """CREATE TABLE normalized_post_versions (
              id INTEGER PRIMARY KEY, normalized_post_id INTEGER NOT NULL
            );
            CREATE TABLE m4_intelligence_instances (
              id INTEGER PRIMARY KEY, m4_intelligence_run_id INTEGER NOT NULL,
              normalized_post_version_id INTEGER NOT NULL, feature_json TEXT NOT NULL,
              input_sha256 TEXT NOT NULL
            );
            CREATE TABLE m4_sequence_patterns (
              id INTEGER PRIMARY KEY, m4_intelligence_run_id INTEGER NOT NULL,
              signature_json TEXT NOT NULL, signature_sha256 TEXT NOT NULL,
              input_sha256 TEXT NOT NULL, member_count INTEGER NOT NULL,
              distinct_source_count INTEGER NOT NULL, confidence TEXT NOT NULL,
              created_at TEXT NOT NULL
            );
            CREATE TABLE m4_sequence_pattern_members (
              m4_sequence_pattern_id INTEGER NOT NULL,
              m4_intelligence_instance_id INTEGER NOT NULL, ordinal INTEGER NOT NULL
            );"""
        )


class M4IntelligenceTest(unittest.TestCase):
    def test_derives_closed_mechanisms_without_source_text(self) -> None:
        feature = build_intelligence_feature(
            {"hook_family": "QUESTION", "hook_subtype": "WHY_QUESTION", "read_more_pressure": 2,
             "expected_action": "CONTINUE_READING", "m1_action_labels": ["ASK"],
             "m1_structure_labels": ["QUESTION_LED", "OPEN_LOOP"]},
            {"availability": "NO_PARENT", "open_loop_score": "UNKNOWN", "closure_score": "UNKNOWN",
             "cliffhanger_technique": "UNKNOWN"},
        )
        self.assertEqual(
            ["QUESTION_GAP", "WITHHELD_REASON"],
            feature["hook"]["continue_reading_mechanisms"],
        )
        self.assertEqual(
            ["CONTINUE_READING", "REPLY_OR_COMMENT"], feature["expected_reader_actions"]
        )
        self.assertEqual("HYPOTHESIS", feature["action_evidence_mode"])
        self.assertNotIn("text", str(feature).lower())
        signature = sequence_signature(feature)
        self.assertEqual("QUESTION", signature["hook_family"])
        self.assertNotIn("text", str(signature).lower())

    def test_persists_only_multi_source_sequence_patterns_idempotently(self) -> None:
        repository = _SequenceRepository()
        feature = build_intelligence_feature(
            {"hook_family": "QUESTION", "hook_subtype": "WHY_QUESTION", "read_more_pressure": 1,
             "expected_action": "CONTINUE_READING", "m1_action_labels": [],
             "m1_structure_labels": ["QUESTION_LED"]},
            {"availability": "NO_PARENT", "open_loop_score": "UNKNOWN", "closure_score": "UNKNOWN",
             "cliffhanger_technique": "UNKNOWN"},
        )
        feature_json = json.dumps(feature, sort_keys=True)
        other_feature = {
            **feature, "hook": {**feature["hook"], "family": "OTHER"}
        }
        repository.connection.executemany(
            "INSERT INTO normalized_post_versions (id, normalized_post_id) VALUES (?, ?)",
            [(1, 10), (2, 11), (3, 12)],
        )
        repository.connection.executemany(
            """INSERT INTO m4_intelligence_instances
            (id, m4_intelligence_run_id, normalized_post_version_id, feature_json, input_sha256)
            VALUES (?, 1, ?, ?, ?)""",
            [(1, 1, feature_json, "a" * 64), (2, 2, feature_json, "b" * 64),
             (3, 3, json.dumps(other_feature), "c" * 64)],
        )
        self.assertEqual(1, materialize_sequence_patterns(repository, 1))
        self.assertEqual(0, materialize_sequence_patterns(repository, 1))
        pattern = repository.connection.execute(
            "SELECT member_count, distinct_source_count FROM m4_sequence_patterns"
        ).fetchone()
        self.assertEqual((2, 2), tuple(pattern))
        count = repository.connection.execute(
            "SELECT COUNT(*) FROM m4_sequence_pattern_members"
        ).fetchone()[0]
        self.assertEqual(2, count)


if __name__ == "__main__":
    unittest.main()
