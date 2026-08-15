import hashlib
import tempfile
import unittest
from pathlib import Path

from social_content_engine.analyzer.mock_adapter import DeterministicMockAdapter
from social_content_engine.analyzer.orchestrator import (
    analyze_normalized_version,
    analyze_post,
)
from social_content_engine.data.repository import Repository
from social_content_engine.intelligence.parent_ending import (
    build_parent_ending_feature,
    extract_parent_ending,
)


def add_post(repository: Repository, post_id: str, text: str) -> int:
    repository.upsert_normalized_post(
        {
            "schema_version": 1,
            "source": "threads",
            "source_post_id": post_id,
            "author_id": None,
            "username": "fixture",
            "text": text,
            "permalink": None,
            "published_at": None,
            "media_type": "TEXT_POST",
            "raw_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "normalized_at": "2026-08-16T00:00:00+00:00",
        }
    )
    return int(
        repository.connection.execute(
            "SELECT current_version_id FROM normalized_posts WHERE source_post_id = ?",
            (post_id,),
        ).fetchone()[0]
    )


def analyze(repository: Repository, post_id: str, run_id: str) -> int:
    return analyze_post(
        repository,
        post_id,
        DeterministicMockAdapter(),
        now=lambda: "2026-08-16T00:01:00+00:00",
        new_run_id=lambda: run_id,
    ).analysis_run_row_id


def relate(repository: Repository, child: str, parent: str) -> None:
    repository.connection.execute(
        """INSERT INTO thread_relationships
        (source, child_post_id, parent_post_id, root_post_id, relationship_type, observed_at)
        VALUES ('threads', ?, ?, ?, 'REPLY_TO', '2026-08-16T00:02:00+00:00')""",
        (child, parent, parent),
    )
    repository.connection.commit()


class ParentEndingTest(unittest.TestCase):
    def test_last_one_two_three_lines_span_hash_scores_and_matching_labels(self) -> None:
        parent_text = "first\r\n  second  \r\nなぜ？  "
        with tempfile.TemporaryDirectory() as directory:
            with Repository(Path(directory) / "test.sqlite3") as repository:
                add_post(repository, "parent", parent_text)
                add_post(repository, "child", "reply")
                analyze(repository, "parent", "parent-run")
                child_run = analyze(repository, "child", "child-run")
                relate(repository, "child", "parent")
                result = extract_parent_ending(
                    repository,
                    child_run,
                    extracted_at=lambda: "2026-08-16T00:03:00+00:00",
                )
                feature = result["feature"]
                self.assertEqual("OBSERVED", feature["availability"])
                counts = [item["non_empty_line_count"] for item in feature["windows"]]
                self.assertEqual([1, 2, 3], counts)
                for window in feature["windows"]:
                    value = parent_text[window["start"] : window["end"]]
                    self.assertEqual(len(value), window["char_count"])
                    self.assertEqual(
                        hashlib.sha256(value.encode("utf-8")).hexdigest(),
                        window["text_sha256"],
                    )
                self.assertEqual("QUESTION", feature["terminal_mark"])
                self.assertEqual(2, feature["open_loop_score"])
                self.assertEqual(0, feature["closure_score"])
                self.assertEqual(2, feature["continuation_desire"])
                self.assertEqual("UNANSWERED_QUESTION", feature["cliffhanger_technique"])
                self.assertEqual(["ASK"], feature["m1_action_labels"])
                self.assertIn("SHORT_PUNCHY", feature["m1_structure_labels"])

    def test_availability_states_come_only_from_relationship_ssot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with Repository(Path(directory) / "test.sqlite3") as repository:
                add_post(repository, "child", "reply")
                child_run = analyze(repository, "child", "child-run")
                no_parent = extract_parent_ending(repository, child_run)
                self.assertEqual("NO_PARENT", no_parent["feature"]["availability"])

        with tempfile.TemporaryDirectory() as directory:
            with Repository(Path(directory) / "test.sqlite3") as repository:
                add_post(repository, "child", "reply")
                child_run = analyze(repository, "child", "child-run")
                relate(repository, "child", "missing")
                unavailable = extract_parent_ending(repository, child_run)
                self.assertEqual(
                    "PARENT_TEXT_UNAVAILABLE", unavailable["feature"]["availability"]
                )

        with tempfile.TemporaryDirectory() as directory:
            with Repository(Path(directory) / "test.sqlite3") as repository:
                add_post(repository, "child", "reply")
                child_run = analyze(repository, "child", "child-run")
                relate(repository, "child", "parent-a")
                relate(repository, "child", "parent-b")
                ambiguous = extract_parent_ending(repository, child_run)
                self.assertEqual(
                    "RELATIONSHIP_AMBIGUOUS", ambiguous["feature"]["availability"]
                )

    def test_parent_labels_require_matching_analyzer_and_taxonomy_versions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with Repository(Path(directory) / "test.sqlite3") as repository:
                parent_version = add_post(repository, "parent", "なぜ？")
                add_post(repository, "child", "reply")
                analyze_normalized_version(
                    repository,
                    parent_version,
                    DeterministicMockAdapter(),
                    analyzer_version="different-analyzer-v1",
                    new_run_id=lambda: "different-parent-run",
                )
                child_run = analyze(repository, "child", "child-run")
                relate(repository, "child", "parent")
                feature = extract_parent_ending(repository, child_run)["feature"]
                self.assertEqual([], feature["m1_action_labels"])
                self.assertEqual([], feature["m1_structure_labels"])

    def test_marker_rules_empty_parent_replay_and_no_text_leakage(self) -> None:
        continuation = build_parent_ending_feature("OBSERVED", "本文\n続きは次回")
        self.assertEqual("EXPLICIT_CONTINUATION", continuation["cliffhanger_technique"])
        self.assertEqual((3, 0, 3), (
            continuation["open_loop_score"],
            continuation["closure_score"],
            continuation["continuation_desire"],
        ))
        empty = build_parent_ending_feature("OBSERVED", " \r\n\t")
        self.assertEqual("PARENT_TEXT_UNAVAILABLE", empty["availability"])
        self.assertEqual("UNKNOWN", empty["open_loop_score"])

        source_text = "秘密の本文\n続きは次回"
        with tempfile.TemporaryDirectory() as directory:
            with Repository(Path(directory) / "test.sqlite3") as repository:
                add_post(repository, "parent", source_text)
                add_post(repository, "child", "reply")
                analyze(repository, "parent", "parent-run")
                child_run = analyze(repository, "child", "child-run")
                relate(repository, "child", "parent")
                first = extract_parent_ending(repository, child_run)
                replay = extract_parent_ending(repository, child_run)
                self.assertFalse(first["reused"])
                self.assertTrue(replay["reused"])
                row = repository.connection.execute(
                    "SELECT feature_json FROM parent_ending_features"
                ).fetchone()
                self.assertNotIn(source_text, row["feature_json"])
                self.assertNotIn('"text"', row["feature_json"])
                self.assertNotIn('"quote"', row["feature_json"])
                migration = repository.connection.execute(
                    "SELECT migration_sha256 FROM schema_migrations WHERE version = 6"
                ).fetchone()
                self.assertRegex(migration["migration_sha256"], r"^[0-9a-f]{64}$")

    def test_persistence_rejects_forbidden_source_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with Repository(Path(directory) / "test.sqlite3") as repository:
                add_post(repository, "child", "reply")
                child_run = analyze(repository, "child", "child-run")
                source = repository.get_analysis_feature_source(child_run)
                for feature in (
                    {"text": "leak"},
                    {"nested": {"quote": "leak"}},
                    {"permalink": "https://example.test"},
                    {"username": "fixture"},
                ):
                    with self.subTest(feature=feature):
                        with self.assertRaisesRegex(ValueError, "source text"):
                            repository.persist_parent_ending_feature(
                                child_analysis_run_row_id=child_run,
                                child_normalized_post_version_id=int(
                                    source["normalized_post_version_id"]
                                ),
                                parent_normalized_post_version_id=None,
                                parent_analysis_run_row_id=None,
                                extractor_version="negative",
                                feature_contract_version="M2_PARENT_ENDING_V1",
                                input_sha256=str(source["input_sha256"]),
                                feature=feature,
                                extracted_at="2026-08-16T00:03:00+00:00",
                            )


if __name__ == "__main__":
    unittest.main()
