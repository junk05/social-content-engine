import json
import tempfile
import unittest
from pathlib import Path

from social_content_engine.data.repository import Repository
from social_content_engine.intelligence.pattern_report import (
    build_pattern_report,
    render_pattern_report_markdown,
    write_pattern_report,
)
from tests.test_pattern_miner import add_member, build_fixture, mine


def fixed_now() -> str:
    return "2026-08-16T00:04:00+00:00"


class PatternReportTest(unittest.TestCase):
    def test_parent_support_precedes_author_coverage_when_support_and_distinct_tie(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with Repository(Path(directory) / "test.sqlite3") as repository:
                for parent_id in ("parent-1", "parent-2"):
                    repository.upsert_normalized_post(
                        {
                            "schema_version": 1,
                            "source": "threads",
                            "source_post_id": parent_id,
                            "author_id": None,
                            "username": None,
                            "text": "続きは次回",
                            "permalink": None,
                            "published_at": None,
                            "media_type": "TEXT_POST",
                            "raw_sha256": "9" * 64,
                            "normalized_at": "2026-08-16T00:00:00+00:00",
                        }
                    )
                snapshot_id = repository.create_dataset_snapshot(
                    "coverage-vs-parent", 1, {"fixture": "ranking"}
                )
                add_member(
                    repository,
                    snapshot_id,
                    "coverage-1",
                    "どう？",
                    0,
                    author_id="author-a",
                )
                add_member(
                    repository,
                    snapshot_id,
                    "coverage-2",
                    "本当？",
                    1,
                    author_id="author-a",
                )
                add_member(
                    repository,
                    snapshot_id,
                    "parent-strong-1",
                    "なぜ？",
                    2,
                    author_id="author-b",
                    parent_id="parent-1",
                )
                add_member(
                    repository,
                    snapshot_id,
                    "parent-strong-2",
                    "なぜなの？",
                    3,
                    parent_id="parent-2",
                )
                repository.finalize_dataset_snapshot(snapshot_id)
                result = mine(repository, snapshot_id)
                self.assertEqual(2, len(result["patterns"]))
                first, second = result["patterns"]
                self.assertEqual(1, first["ranking_evidence"]["author_coverage_count"])
                self.assertEqual(2, second["ranking_evidence"]["author_coverage_count"])
                self.assertEqual(
                    2, first["ranking_evidence"]["parent_ending_evidence_support"]
                )
                self.assertEqual(
                    0, second["ranking_evidence"]["parent_ending_evidence_support"]
                )

    def test_ranking_prioritizes_member_then_distinct_author_and_displays_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with Repository(Path(directory) / "test.sqlite3") as repository:
                snapshot_id = repository.create_dataset_snapshot(
                    "ranking", 1, {"fixture": "ranking"}
                )
                fixtures = (
                    ("plain-1", "plain one", None),
                    ("plain-2", "plain two", None),
                    ("plain-3", "plain three", None),
                    ("direct-1", "どう？", "author-a"),
                    ("direct-2", "本当？", "author-b"),
                    ("why-1", "なぜ？", "author-c"),
                    ("why-2", "なぜなの？", "author-c"),
                )
                for ordinal, (post_id, text, author_id) in enumerate(fixtures):
                    add_member(
                        repository,
                        snapshot_id,
                        post_id,
                        text,
                        ordinal,
                        author_id=author_id,
                    )
                repository.finalize_dataset_snapshot(snapshot_id)
                result = mine(repository, snapshot_id)
                self.assertEqual([3, 2, 2], [
                    item["ranking_evidence"]["member_support"]
                    for item in result["patterns"]
                ])
                self.assertEqual([0, 2, 1], [
                    item["ranking_evidence"]["distinct_observed_author_support"]
                    for item in result["patterns"]
                ])
                report = build_pattern_report(
                    repository, dataset_snapshot_id=snapshot_id, generated_at=fixed_now
                )
                self.assertEqual([1, 2, 3], [
                    candidate["rank"] for candidate in report["candidates"]
                ])

    def test_json_markdown_runtime_evidence_warnings_and_no_db_leakage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with Repository(Path(directory) / "test.sqlite3") as repository:
                snapshot_id = build_fixture(repository, ("q1", "q2", "s1"))
                mine(repository, snapshot_id)
                report = build_pattern_report(
                    repository, dataset_snapshot_id=snapshot_id, generated_at=fixed_now
                )
                self.assertEqual(1, report["candidate_count"])
                candidate = report["candidates"][0]
                self.assertEqual(1, candidate["rank"])
                self.assertEqual(2, candidate["member_count"])
                self.assertEqual(2, candidate["ranking_evidence"]["member_support"])
                self.assertEqual(
                    0,
                    candidate["ranking_evidence"]["distinct_observed_author_support"],
                )
                self.assertEqual(0, candidate["ranking_evidence"]["author_coverage_count"])
                self.assertEqual(2, candidate["ranking_evidence"]["author_coverage_total"])
                for instance in candidate["instances"]:
                    self.assertIsNotNone(instance["first_line_evidence_display"])
                    self.assertIsNone(instance["parent_ending_evidence_display"])
                    self.assertIn("AUTHOR_ID_UNAVAILABLE", instance["warnings"])
                    self.assertIn("PARENT_ENDING_NO_PARENT", instance["warnings"])
                markdown = render_pattern_report_markdown(report)
                self.assertIn("[ ] APPROVE  [ ] REJECT", markdown)
                self.assertIn("no virality or effect prediction", markdown)
                self.assertIn("なぜ", markdown)
                database_text = "\n".join(
                    str(row[0])
                    for table, column in (
                        ("patterns", "feature_signature_json"),
                        ("patterns", "ranking_json"),
                        ("patterns", "provenance_json"),
                        ("pattern_instances", "feature_json"),
                    )
                    for row in repository.connection.execute(
                        "SELECT " + column + " FROM " + table
                    ).fetchall()
                )
                self.assertNotIn("なぜ？", database_text)
                self.assertNotIn('"quote"', database_text)

    def test_replay_and_written_artifacts_are_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with Repository(root / "test.sqlite3") as repository:
                snapshot_id = build_fixture(repository, ("q1", "q2", "s1"))
                mine(repository, snapshot_id)
                first = build_pattern_report(
                    repository, dataset_snapshot_id=snapshot_id, generated_at=fixed_now
                )
                second = build_pattern_report(
                    repository, dataset_snapshot_id=snapshot_id, generated_at=fixed_now
                )
                self.assertEqual(first, second)
                write_pattern_report(first, root / "report.json", root / "report.md")
                self.assertEqual(
                    first,
                    json.loads((root / "report.json").read_text(encoding="utf-8")),
                )
                self.assertEqual(
                    render_pattern_report_markdown(first),
                    (root / "report.md").read_text(encoding="utf-8"),
                )

    def test_synthetic_fixture_supports_ten_review_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with Repository(Path(directory) / "test.sqlite3") as repository:
                snapshot_id = build_fixture(repository, ("q1", "q2", "s1"))
                result = mine(repository, snapshot_id)
                original_id = result["patterns"][0]["pattern_id"]
                original = repository.connection.execute(
                    "SELECT * FROM patterns WHERE id = ?", (original_id,)
                ).fetchone()
                original_instances = repository.connection.execute(
                    "SELECT * FROM pattern_instances WHERE pattern_id = ? ORDER BY id",
                    (original_id,),
                ).fetchall()
                for rank in range(2, 11):
                    cursor = repository.connection.execute(
                        """INSERT INTO patterns
                        (pattern_key, version, feature_signature_json,
                         feature_signature_sha256, member_count, ranking_json,
                         provenance_json, review_status, created_at)
                        VALUES (?, 1, ?, ?, 2, ?, ?, 'PENDING', ?)""",
                        (
                            "synthetic-pattern-" + str(rank),
                            original["feature_signature_json"],
                            original["feature_signature_sha256"],
                            json.dumps(
                                {
                                    "method": "support-author-parent-completeness-v1",
                                    "score": 2,
                                    "rank": rank,
                                },
                                separators=(",", ":"),
                                sort_keys=True,
                            ),
                            original["provenance_json"],
                            original["created_at"],
                        ),
                    )
                    pattern_id = int(cursor.lastrowid)
                    for instance in original_instances:
                        repository.connection.execute(
                            """INSERT INTO pattern_instances
                            (pattern_id, source, source_post_id, analysis_run_row_id,
                             normalized_post_version_id, normalized_version,
                             first_line_feature_id, parent_ending_feature_id,
                             extractor_version, feature_contract_version, input_sha256,
                             feature_json, feature_sha256, created_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                            (pattern_id,) + tuple(instance)[2:],
                        )
                repository.connection.commit()
                report = build_pattern_report(
                    repository, dataset_snapshot_id=snapshot_id, generated_at=fixed_now
                )
                self.assertEqual(10, report["candidate_count"])
                self.assertEqual(list(range(1, 11)), [
                    candidate["rank"] for candidate in report["candidates"]
                ])


if __name__ == "__main__":
    unittest.main()
