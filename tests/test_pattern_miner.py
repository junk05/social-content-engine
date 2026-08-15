import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from social_content_engine.analyzer.contracts import TAXONOMY_VERSION
from social_content_engine.analyzer.mock_adapter import DeterministicMockAdapter
from social_content_engine.analyzer.orchestrator import (
    ANALYZER_VERSION,
    MODEL_NAME,
    MODEL_PARAMETERS,
    MODEL_PROVIDER,
    PROMPT_VERSION,
    analyze_normalized_version,
    analyze_post,
)
from social_content_engine.data.repository import Repository, pattern_instance_input_sha256
from social_content_engine.intelligence.first_line import (
    EXTRACTOR_VERSION as FIRST_EXTRACTOR_VERSION,
)
from social_content_engine.intelligence.first_line import extract_first_line
from social_content_engine.intelligence.parent_ending import (
    EXTRACTOR_VERSION as ENDING_EXTRACTOR_VERSION,
)
from social_content_engine.intelligence.parent_ending import extract_parent_ending
from social_content_engine.intelligence.pattern_miner import mine_patterns


def add_member(
    repository: Repository,
    snapshot_id: int,
    post_id: str,
    text: str,
    ordinal: int,
    model_parameters: dict = None,
) -> None:
    raw = json.dumps({"id": post_id, "text": text}, ensure_ascii=False).encode("utf-8")
    run_id = repository.add_collection_run(
        endpoint="/fixture",
        request={"post_id": post_id},
        started_at="2026-08-16T00:00:00+00:00",
        completed_at="2026-08-16T00:00:01+00:00",
        http_status=200,
        response_headers={},
        raw_response=raw,
        raw_response_sha256=hashlib.sha256(raw).hexdigest(),
        collector_version="test",
    )
    raw_id = repository.add_raw_post(
        collection_run_id=run_id,
        source_post_id=post_id,
        raw_json=raw,
        raw_sha256=hashlib.sha256(raw).hexdigest(),
        retrieved_at="2026-08-16T00:00:01+00:00",
    )
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
            "raw_sha256": hashlib.sha256(raw).hexdigest(),
            "normalized_at": "2026-08-16T00:00:01+00:00",
        },
        source_raw_post_id=raw_id,
    )
    version_id = int(
        repository.connection.execute(
            "SELECT current_version_id FROM normalized_posts WHERE source_post_id = ?",
            (post_id,),
        ).fetchone()[0]
    )
    repository.add_dataset_member(
        snapshot_id, version_id, raw_id, ordinal, {"reason": "fixture"}
    )
    if model_parameters is None:
        analysis = analyze_post(
            repository,
            post_id,
            DeterministicMockAdapter(),
            now=lambda: "2026-08-16T00:01:00+00:00",
            new_run_id=lambda: "run-" + post_id,
        )
    else:
        analysis = analyze_normalized_version(
            repository,
            version_id,
            DeterministicMockAdapter(),
            model_parameters=model_parameters,
            now=lambda: "2026-08-16T00:01:00+00:00",
            new_run_id=lambda: "run-" + post_id,
        )
    extract_first_line(
        repository,
        analysis.analysis_run_row_id,
        extracted_at=lambda: "2026-08-16T00:02:00+00:00",
    )
    extract_parent_ending(
        repository,
        analysis.analysis_run_row_id,
        extracted_at=lambda: "2026-08-16T00:02:00+00:00",
    )


def build_fixture(
    repository: Repository, order: tuple, model_parameters: dict = None
) -> int:
    snapshot_id = repository.create_dataset_snapshot("patterns", 1, {"fixture": True})
    content = {"q1": "なぜ？", "q2": "なぜだろう？", "s1": "plain statement"}
    for ordinal, post_id in enumerate(order):
        add_member(
            repository,
            snapshot_id,
            post_id,
            content[post_id],
            ordinal,
            model_parameters,
        )
    repository.finalize_dataset_snapshot(snapshot_id)
    return snapshot_id


def mine(
    repository: Repository, snapshot_id: int, model_parameters: dict = None
) -> dict:
    return mine_patterns(
        repository,
        dataset_snapshot_id=snapshot_id,
        analyzer_version=ANALYZER_VERSION,
        taxonomy_version=TAXONOMY_VERSION,
        prompt_version=PROMPT_VERSION,
        model_provider=MODEL_PROVIDER,
        model_name=MODEL_NAME,
        model_parameters=MODEL_PARAMETERS if model_parameters is None else model_parameters,
        first_line_extractor_version=FIRST_EXTRACTOR_VERSION,
        parent_ending_extractor_version=ENDING_EXTRACTOR_VERSION,
        now=lambda: "2026-08-16T00:03:00+00:00",
    )


def stable_result(result: dict) -> dict:
    patterns = [
        {key: value for key, value in pattern.items() if key != "pattern_id"}
        for pattern in result["patterns"]
    ]
    return {"patterns": patterns, "singletons": result["singletons"]}


class PatternMinerTest(unittest.TestCase):
    def test_two_plus_one_promotes_only_multi_member_cluster(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with Repository(Path(directory) / "test.sqlite3") as repository:
                result = mine(repository, build_fixture(repository, ("q1", "q2", "s1")))
                self.assertEqual(3, result["selected_instance_count"])
                self.assertEqual(1, len(result["patterns"]))
                self.assertEqual(1, len(result["singletons"]))
                pattern = result["patterns"][0]
                self.assertEqual(2, pattern["member_count"])
                self.assertTrue(pattern["exact_match"])
                self.assertEqual(0, pattern["distance"])
                self.assertEqual(["ASK"], pattern["labels"]["actions"])
                self.assertEqual(
                    ["QUESTION_LED", "SHORT_PUNCHY"],
                    pattern["labels"]["structures"],
                )
                self.assertEqual(1, repository.count("patterns"))
                self.assertEqual(2, repository.count("pattern_instances"))

    def test_order_independence_cluster_rank_and_hash(self) -> None:
        results = []
        for order in (("q1", "q2", "s1"), ("s1", "q2", "q1")):
            with tempfile.TemporaryDirectory() as directory:
                with Repository(Path(directory) / "test.sqlite3") as repository:
                    snapshot_id = build_fixture(repository, order)
                    results.append(stable_result(mine(repository, snapshot_id)))
        self.assertEqual(results[0], results[1])

    def test_replay_preserves_review_and_feature_provenance_without_leakage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with Repository(Path(directory) / "test.sqlite3") as repository:
                snapshot_id = build_fixture(repository, ("q1", "q2", "s1"))
                first = mine(repository, snapshot_id)
                pattern_id = first["patterns"][0]["pattern_id"]
                repository.review_pattern(pattern_id, "APPROVED")
                replay = mine(repository, snapshot_id)
                self.assertEqual(pattern_id, replay["patterns"][0]["pattern_id"])
                pattern = repository.connection.execute(
                    "SELECT * FROM patterns WHERE id = ?", (pattern_id,)
                ).fetchone()
                self.assertEqual("APPROVED", pattern["review_status"])
                self.assertEqual(2, repository.count("pattern_instances"))
                rows = repository.connection.execute(
                    """SELECT pattern_instances.*, analysis_runs.input_sha256 AS analysis_input,
                              first_line_features.input_sha256 AS first_input,
                              first_line_features.feature_sha256 AS first_feature,
                              parent_ending_features.input_sha256 AS ending_input,
                              parent_ending_features.feature_sha256 AS ending_feature
                    FROM pattern_instances
                    JOIN analysis_runs ON analysis_runs.id = pattern_instances.analysis_run_row_id
                    JOIN first_line_features
                      ON first_line_features.id = pattern_instances.first_line_feature_id
                    JOIN parent_ending_features
                      ON parent_ending_features.id = pattern_instances.parent_ending_feature_id
                    ORDER BY pattern_instances.source_post_id"""
                ).fetchall()
                for row in rows:
                    expected = pattern_instance_input_sha256(
                        analysis_input_sha256=row["analysis_input"],
                        first_line_input_sha256=row["first_input"],
                        first_line_feature_sha256=row["first_feature"],
                        parent_ending_input_sha256=row["ending_input"],
                        parent_ending_feature_sha256=row["ending_feature"],
                    )
                    self.assertEqual(expected, row["input_sha256"])
                    self.assertNotIn('"text"', row["feature_json"])
                    self.assertNotIn('"quote"', row["feature_json"])
                self.assertNotIn('"text"', pattern["feature_signature_json"])
                self.assertNotIn('"quote"', pattern["feature_signature_json"])

    def test_requires_finalized_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with Repository(Path(directory) / "test.sqlite3") as repository:
                snapshot_id = repository.create_dataset_snapshot("draft", 1, {"fixture": True})
                with self.assertRaisesRegex(ValueError, "finalized"):
                    mine(repository, snapshot_id)

    def test_selects_nested_non_empty_canonical_model_parameters(self) -> None:
        parameters = {
            "temperature": 0,
            "response": {"format": "json", "strict": True},
            "stop": ["END", "完了"],
        }
        with tempfile.TemporaryDirectory() as directory:
            with Repository(Path(directory) / "test.sqlite3") as repository:
                snapshot_id = build_fixture(
                    repository, ("q1", "q2", "s1"), parameters
                )
                result = mine(repository, snapshot_id, parameters)
                self.assertEqual(3, result["selected_instance_count"])
                self.assertEqual(1, len(result["patterns"]))
                stored = repository.connection.execute(
                    "SELECT model_parameters_json FROM analysis_runs LIMIT 1"
                ).fetchone()[0]
                self.assertEqual(
                    json.dumps(
                        parameters,
                        ensure_ascii=False,
                        separators=(",", ":"),
                        sort_keys=True,
                    ),
                    stored,
                )


if __name__ == "__main__":
    unittest.main()
