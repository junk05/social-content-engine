import hashlib
import sqlite3
import tempfile
import unittest
from pathlib import Path

from social_content_engine.data.repository import (
    Repository,
    pattern_instance_input_sha256,
    pattern_set_input_sha256,
)

SIGNATURE = {
    "first_line_hook_family": "QUESTION",
    "first_line_hook_subtype": "DIRECT_QUESTION",
    "parent_ending_availability": "NO_PARENT",
    "parent_cliffhanger_technique": "UNKNOWN",
}


def downgrade_to_legacy_pattern_tables(path: Path, *, with_data: bool) -> None:
    connection = sqlite3.connect(path)
    connection.execute("DROP TABLE pattern_instances")
    connection.execute("DROP TABLE patterns")
    connection.execute(
        """CREATE TABLE patterns (
          id INTEGER PRIMARY KEY, pattern_key TEXT NOT NULL UNIQUE, payload_json TEXT NOT NULL
        )"""
    )
    connection.execute(
        """CREATE TABLE pattern_instances (
          id INTEGER PRIMARY KEY,
          pattern_id INTEGER NOT NULL REFERENCES patterns(id),
          source_post_id TEXT NOT NULL,
          analysis_run_id INTEGER NOT NULL REFERENCES analysis_runs(id)
        )"""
    )
    if with_data:
        connection.execute(
            "INSERT INTO patterns (pattern_key, payload_json) VALUES ('legacy', '{}')"
        )
    connection.execute("DELETE FROM schema_migrations WHERE version = 7")
    connection.commit()
    connection.close()


def add_evidence(repository: Repository, source_post_id: str, snapshot_id: int) -> dict:
    body = ("{\"data\":[{\"id\":\"" + source_post_id + "\"}]}").encode("utf-8")
    run_id = repository.add_collection_run(
        endpoint="/keyword_search",
        request={"params": {"q": "fixture"}},
        started_at="2026-08-16T00:00:00+00:00",
        completed_at="2026-08-16T00:00:01+00:00",
        http_status=200,
        response_headers={},
        raw_response=body,
        raw_response_sha256=hashlib.sha256(body).hexdigest(),
        collector_version="fixture",
    )
    raw_json = ("{\"id\":\"" + source_post_id + "\"}").encode("utf-8")
    raw_sha = hashlib.sha256(raw_json).hexdigest()
    raw_id = repository.add_raw_post(
        collection_run_id=run_id,
        source_post_id=source_post_id,
        raw_json=raw_json,
        raw_sha256=raw_sha,
        retrieved_at="2026-08-16T00:00:01+00:00",
    )
    repository.upsert_normalized_post(
        {
            "schema_version": 1,
            "source": "threads",
            "source_post_id": source_post_id,
            "author_id": None,
            "username": None,
            "text": "質問ですか？",
            "permalink": None,
            "published_at": None,
            "media_type": "TEXT_POST",
            "raw_sha256": raw_sha,
            "normalized_at": "2026-08-16T00:00:01+00:00",
        },
        source_raw_post_id=raw_id,
    )
    normalized = repository.get_normalized_post(source_post_id)
    version_id = int(normalized["current_version_id"])
    repository.add_dataset_member(
        snapshot_id,
        version_id,
        raw_id,
        repository.count("dataset_members"),
        {"rule": "fixture"},
    )
    analysis_id = repository.start_analysis_run(
        {
            "analysis_run_id": "run-" + source_post_id,
            "source": "threads",
            "source_post_id": source_post_id,
            "normalized_post_version": 1,
            "normalized_post_version_id": version_id,
            "analyzer_version": "m1",
            "taxonomy_version": "M1_TAXONOMY_V1",
            "prompt_version": "prompt",
            "model_provider": "deterministic",
            "model_name": "mock",
            "model_parameters": {},
            "input_sha256": "1" * 64,
            "analyzed_at": "2026-08-16T00:01:00+00:00",
        }
    )
    repository.persist_analysis(analysis_id, source_post_id, {}, "2" * 64)
    first = repository.persist_first_line_feature(
        analysis_run_row_id=analysis_id,
        normalized_post_version_id=version_id,
        extractor_version="first-v1",
        feature_contract_version="FIRST_V1",
        input_sha256="1" * 64,
        feature={
            "availability": "OBSERVED",
            "start": 0,
            "end": 6,
            "text_sha256": "3" * 64,
            "char_count": 6,
            "terminal_mark": "QUESTION",
            "hook_family": "QUESTION",
            "hook_subtype": "DIRECT_QUESTION",
            "curiosity_gap": 2,
            "self_relevance": 0,
            "target_specificity": 0,
            "emotional_intensity": 0,
            "contrarian_level": 0,
            "read_more_pressure": 0,
            "expected_action": "ANSWER",
            "m1_action_labels": [],
            "m1_structure_labels": [],
        },
        extracted_at="2026-08-16T00:02:00+00:00",
    )
    ending = repository.persist_parent_ending_feature(
        child_analysis_run_row_id=analysis_id,
        child_normalized_post_version_id=version_id,
        parent_normalized_post_version_id=None,
        parent_analysis_run_row_id=None,
        extractor_version="ending-v1",
        feature_contract_version="ENDING_V1",
        input_sha256="1" * 64,
        feature={
            "availability": "NO_PARENT",
            "windows": [],
            "terminal_mark": "NONE",
            "open_loop_score": "UNKNOWN",
            "closure_score": "UNKNOWN",
            "continuation_desire": "UNKNOWN",
            "cliffhanger_technique": "UNKNOWN",
            "m1_action_labels": [],
            "m1_structure_labels": [],
        },
        extracted_at="2026-08-16T00:02:00+00:00",
    )
    instance_input_sha256 = pattern_instance_input_sha256(
        analysis_input_sha256="1" * 64,
        first_line_input_sha256="1" * 64,
        first_line_feature_sha256=str(first["feature_sha256"]),
        parent_ending_input_sha256="1" * 64,
        parent_ending_feature_sha256=str(ending["feature_sha256"]),
    )
    return {
        "source": "threads",
        "source_post_id": source_post_id,
        "analysis_run_row_id": analysis_id,
        "normalized_post_version_id": version_id,
        "first_line_feature_id": first["id"],
        "parent_ending_feature_id": ending["id"],
        "extractor_version": "pattern-v1",
        "feature_contract_version": "PATTERN_INSTANCE_V1",
        "input_sha256": instance_input_sha256,
        "feature": dict(SIGNATURE),
        "created_at": "2026-08-16T00:03:00+00:00",
    }


class PatternRepositoryTest(unittest.TestCase):
    def build_evidence(self, repository: Repository) -> tuple:
        snapshot_id = repository.create_dataset_snapshot(
            "patterns", 1, {"selection": "fixture"}
        )
        instances = (
            add_evidence(repository, "post-1", snapshot_id),
            add_evidence(repository, "post-2", snapshot_id),
        )
        repository.finalize_dataset_snapshot(snapshot_id)
        return snapshot_id, instances

    def create_pattern(
        self,
        repository: Repository,
        snapshot_id: int,
        instances: tuple,
        ranking: dict = None,
        provenance_input_sha256: str = None,
    ) -> int:
        set_input_sha256 = pattern_set_input_sha256(
            [str(instance["input_sha256"]) for instance in instances], SIGNATURE
        )
        return repository.create_pattern(
            pattern_key="question-no-parent",
            version=1,
            feature_signature=dict(SIGNATURE),
            ranking=ranking or {"method": "member-count-v1", "score": 2, "rank": 1},
            provenance={
                "dataset_snapshot_id": snapshot_id,
                "miner_version": "miner-v1",
                "feature_contract_version": "PATTERN_V1",
                "input_sha256": provenance_input_sha256 or set_input_sha256,
            },
            review_status="PENDING",
            instances=instances,
            created_at="2026-08-16T00:04:00+00:00",
        )

    def test_persists_closed_pattern_with_two_distinct_sources_and_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with Repository(Path(directory) / "test.sqlite3") as repository:
                snapshot_id, instances = self.build_evidence(repository)
                pattern_id = self.create_pattern(repository, snapshot_id, instances)
                pattern = repository.connection.execute(
                    "SELECT * FROM patterns WHERE id = ?", (pattern_id,)
                ).fetchone()
                self.assertEqual(2, pattern["member_count"])
                signature_json = str(pattern["feature_signature_json"])
                self.assertEqual(
                    hashlib.sha256(signature_json.encode("utf-8")).hexdigest(),
                    pattern["feature_signature_sha256"],
                )
                rows = repository.connection.execute(
                    "SELECT * FROM pattern_instances ORDER BY source_post_id"
                ).fetchall()
                self.assertEqual(["post-1", "post-2"], [row["source_post_id"] for row in rows])
                for row in rows:
                    self.assertEqual(1, row["normalized_version"])
                    self.assertEqual(
                        hashlib.sha256(str(row["feature_json"]).encode("utf-8")).hexdigest(),
                        row["feature_sha256"],
                    )
                repository.review_pattern(pattern_id, "APPROVED")
                with self.assertRaises(ValueError):
                    repository.review_pattern(pattern_id, "REJECTED")

    def test_rejects_single_source_and_text_or_identity_leakage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with Repository(Path(directory) / "test.sqlite3") as repository:
                snapshot_id, instances = self.build_evidence(repository)
                with self.assertRaisesRegex(ValueError, "two distinct"):
                    self.create_pattern(repository, snapshot_id, (instances[0], instances[0]))
                leaked = dict(instances[1])
                leaked_feature = dict(SIGNATURE)
                leaked_feature["quote"] = "原文"
                leaked["feature"] = leaked_feature
                with self.assertRaisesRegex(ValueError, "source text or identity"):
                    self.create_pattern(repository, snapshot_id, (instances[0], leaked))
                with self.assertRaisesRegex(ValueError, "source text or identity"):
                    self.create_pattern(
                        repository,
                        snapshot_id,
                        instances,
                        ranking={
                            "method": "member-count-v1",
                            "score": 2,
                            "rank": 1,
                            "summary": "freeform is forbidden",
                        },
                    )

    def test_rejects_mismatched_feature_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with Repository(Path(directory) / "test.sqlite3") as repository:
                snapshot_id, instances = self.build_evidence(repository)
                wrong = dict(instances[1])
                wrong["first_line_feature_id"] = instances[0]["first_line_feature_id"]
                with self.assertRaisesRegex(ValueError, "provenance is inconsistent"):
                    self.create_pattern(repository, snapshot_id, (instances[0], wrong))

    def test_rejects_well_formed_but_tampered_instance_input_hash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with Repository(Path(directory) / "test.sqlite3") as repository:
                snapshot_id, instances = self.build_evidence(repository)
                tampered = dict(instances[1])
                tampered["input_sha256"] = "f" * 64
                with self.assertRaisesRegex(ValueError, "does not match feature evidence"):
                    self.create_pattern(repository, snapshot_id, (instances[0], tampered))

    def test_rejects_well_formed_but_tampered_pattern_set_hash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with Repository(Path(directory) / "test.sqlite3") as repository:
                snapshot_id, instances = self.build_evidence(repository)
                with self.assertRaisesRegex(ValueError, "does not match instance evidence"):
                    self.create_pattern(
                        repository,
                        snapshot_id,
                        instances,
                        provenance_input_sha256="e" * 64,
                    )

    def test_migrates_empty_legacy_tables_idempotently_and_refuses_legacy_data(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            empty_path = Path(directory) / "empty.sqlite3"
            with Repository(empty_path):
                pass
            downgrade_to_legacy_pattern_tables(empty_path, with_data=False)
            with Repository(empty_path) as repository:
                columns = {
                    row["name"]
                    for row in repository.connection.execute(
                        "PRAGMA table_info(pattern_instances)"
                    ).fetchall()
                }
                self.assertIn("first_line_feature_id", columns)
            with Repository(empty_path) as repository:
                self.assertEqual(
                    1,
                    repository.connection.execute(
                        "SELECT COUNT(*) FROM schema_migrations WHERE version = 7"
                    ).fetchone()[0],
                )

            populated_path = Path(directory) / "populated.sqlite3"
            with Repository(populated_path):
                pass
            downgrade_to_legacy_pattern_tables(populated_path, with_data=True)
            with self.assertRaisesRegex(RuntimeError, "migration refused"):
                Repository(populated_path)
            connection = sqlite3.connect(populated_path)
            try:
                legacy_count = connection.execute("SELECT COUNT(*) FROM patterns").fetchone()[0]
                self.assertEqual(1, legacy_count)
                self.assertEqual(
                    0,
                    connection.execute(
                        "SELECT COUNT(*) FROM schema_migrations WHERE version = 7"
                    ).fetchone()[0],
                )
            finally:
                connection.close()

    def test_database_integrity_after_pattern_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with Repository(Path(directory) / "test.sqlite3") as repository:
                snapshot_id, instances = self.build_evidence(repository)
                self.create_pattern(repository, snapshot_id, instances)
                self.assertEqual([], repository.connection.execute(
                    "PRAGMA foreign_key_check"
                ).fetchall())
                self.assertEqual(
                    "ok", repository.connection.execute("PRAGMA integrity_check").fetchone()[0]
                )


if __name__ == "__main__":
    unittest.main()
