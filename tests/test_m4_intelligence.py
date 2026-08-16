import json
import sqlite3
import unittest

from social_content_engine.intelligence.m4_intelligence import (
    build_intelligence_feature,
    materialize_metric_snapshots,
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


class _MetricRepository:
    def __init__(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(
            """CREATE TABLE dataset_members (
              dataset_snapshot_id INTEGER NOT NULL, normalized_post_version_id INTEGER NOT NULL,
              ordinal INTEGER NOT NULL
            );
            CREATE TABLE dataset_snapshots (id INTEGER PRIMARY KEY, finalized_at TEXT NOT NULL);
            CREATE TABLE browser_normalized_bridges (
              normalized_post_version_id INTEGER NOT NULL, browser_post_identity_id INTEGER NOT NULL
            );
            CREATE TABLE browser_observations (
              id INTEGER PRIMARY KEY, browser_post_identity_id INTEGER NOT NULL,
              collected_at TEXT NOT NULL
            );
            CREATE TABLE browser_observed_fields (
              id INTEGER PRIMARY KEY, browser_observation_id INTEGER NOT NULL,
              field_name TEXT NOT NULL, observed_value_json TEXT NOT NULL,
              observed_at TEXT NOT NULL, extractor_version TEXT NOT NULL, surface TEXT NOT NULL
            );
            CREATE TABLE m4_metric_snapshots (
              dataset_snapshot_id INTEGER NOT NULL, normalized_post_version_id INTEGER NOT NULL,
              browser_observation_id INTEGER NOT NULL, field_name TEXT NOT NULL,
              metric_value INTEGER NOT NULL, observed_at TEXT NOT NULL, surface TEXT NOT NULL,
              extractor_version TEXT NOT NULL, input_sha256 TEXT NOT NULL,
              metric_version TEXT NOT NULL,
              UNIQUE(dataset_snapshot_id, browser_observation_id, field_name)
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

    def test_metric_selection_includes_historical_identity_observations_before_snapshot(
        self,
    ) -> None:
        repository = _MetricRepository()
        repository.connection.executescript(
            """INSERT INTO dataset_snapshots VALUES (1, '2026-08-16T01:00:00+00:00');
            INSERT INTO dataset_members VALUES (1, 10, 0);
            INSERT INTO browser_normalized_bridges VALUES (10, 20);
            INSERT INTO browser_observations VALUES (100, 20, '2026-08-16T00:00:00+00:00');
            INSERT INTO browser_observations VALUES (101, 20, '2026-08-16T00:30:00+00:00');
            INSERT INTO browser_observations VALUES (102, 20, '2026-08-16T02:00:00+00:00');
            INSERT INTO browser_observed_fields VALUES
              (1, 100, 'public_counters.like_count', '0',
               '2026-08-16T00:00:00+00:00', 'search-v1', 'threads_search_card'),
              (2, 101, 'public_counters.view_count', '12',
               '2026-08-16T00:30:00+00:00', 'detail-v1', 'threads_post_detail'),
              (3, 102, 'public_counters.reply_count', '3',
               '2026-08-16T02:00:00+00:00', 'detail-v1', 'threads_post_detail');"""
        )
        self.assertEqual(2, materialize_metric_snapshots(repository, 1))
        rows = repository.connection.execute(
            "SELECT browser_observation_id, field_name, metric_value "
            "FROM m4_metric_snapshots ORDER BY browser_observation_id"
        ).fetchall()
        self.assertEqual(
            [(100, "public_counters.like_count", 0), (101, "public_counters.view_count", 12)],
            [tuple(row) for row in rows],
        )


if __name__ == "__main__":
    unittest.main()
