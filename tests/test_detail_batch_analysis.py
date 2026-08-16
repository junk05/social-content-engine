import json
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict

from social_content_engine.analyzer.batch import run_analysis_batch
from social_content_engine.analyzer.mock_adapter import DeterministicMockAdapter
from social_content_engine.data.browser_observation import (
    browser_observation_payload_sha256,
)
from social_content_engine.data.repository import Repository
from social_content_engine.intelligence.clean_dataset import (
    prepare_detail_batch_analysis,
)
from social_content_engine.intelligence.structural import (
    EXTRACTOR_VERSION,
    TAXONOMY_VERSION,
    derive_structural_features,
)
from tests.test_analysis_batch import CONFIG
from tests.test_browser_observation_repository import observation


def browser_observation(
    post_code: str, text: str, observation_type: str
) -> Dict[str, Any]:
    payload = observation(observation_type=observation_type, text=text)
    payload["post_url"] = (
        "https://www.threads.net/@fixture/post/" + post_code
    )
    payload["collection_context"]["surface"] = (
        "threads_post_detail"
        if observation_type == "POST_DETAIL"
        else "threads_search_card"
    )
    for field in payload["observed_fields"]:
        field["surface"] = payload["collection_context"]["surface"]
    payload["payload_sha256"] = browser_observation_payload_sha256(payload)
    return payload


def complete_item(repository: Repository, batch_id: int, post_code: str, text: str) -> None:
    claim = repository.claim_browser_detail(
        batch_id, claimed_at="2026-08-16T01:01:00Z"
    )
    if claim is None:
        raise AssertionError("expected one queue item")
    detail_payload = browser_observation(post_code, text, "POST_DETAIL")
    detail_payload["public_counters"]["view_count"] = 0
    detail_payload["observed_fields"].append(
        {
            "field": "public_counters.view_count",
            "value": 0,
            "surface": "threads_post_detail",
            "observed_at": "2026-08-16T01:02:00Z",
            "extractor_version": "fixture-extractor-v1",
        }
    )
    detail_payload["payload_sha256"] = browser_observation_payload_sha256(
        detail_payload
    )
    detail = repository.add_browser_observation(
        detail_payload,
        detail_attempt={
            "attempted_at": "2026-08-16T01:02:00Z",
            "extractor_version": "fixture-extractor-v1",
            "contract_version": "M3_BROWSER_DETAIL_ATTEMPT_V1",
        },
    )
    repository.complete_browser_detail_queue(
        int(claim["queue_item_id"]),
        batch_id=batch_id,
        attempt=int(claim["attempt"]),
        lease_version=int(claim["lease_version"]),
        detail_observation_id=int(detail["browser_observation_id"]),
        completed_at="2026-08-16T01:03:00Z",
    )


class DetailBatchAnalysisTest(unittest.TestCase):
    def test_completed_batch_builds_clean_delta_for_existing_analysis_and_structure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with Repository(Path(directory) / "analysis.sqlite3") as repository:
                fixtures = (
                    ("ValidA", "あなたへ、なぜ今なの？"),
                    ("Invalid", "3日"),
                    ("ValidB", "まず3つの理由を説明します。"),
                )
                for post_code, text in fixtures:
                    repository.add_browser_observation(
                        browser_observation(post_code, text, "SEARCH_CARD")
                    )
                batch_id = repository.start_browser_detail_batch(
                    requested_items=3,
                    max_items=3,
                    started_at="2026-08-16T01:00:00Z",
                )
                for post_code, text in fixtures:
                    complete_item(repository, batch_id, post_code, text)
                repository.finish_browser_detail_batch(
                    batch_id, completed_at="2026-08-16T01:04:00Z"
                )

                result = prepare_detail_batch_analysis(
                    repository, batch_id, "detail-delta", 1
                )
                self.assertEqual(
                    {
                        "detail_batch_id",
                        "dataset_snapshot_id",
                        "enriched_count",
                        "valid_member_count",
                        "excluded_count",
                        "new_assessment_count",
                    },
                    set(result),
                )
                self.assertEqual(3, result["enriched_count"])
                self.assertEqual(2, result["valid_member_count"])
                self.assertEqual(1, result["excluded_count"])
                serialized = json.dumps(result)
                for forbidden in (
                    "threads.net",
                    "あなた",
                    "fixture",
                    "author",
                    "text",
                    "url",
                ):
                    self.assertNotIn(forbidden, serialized.lower())

                snapshot_id = result["dataset_snapshot_id"]
                snapshot = repository.connection.execute(
                    "SELECT status FROM dataset_snapshots WHERE id = ?",
                    (snapshot_id,),
                ).fetchone()
                self.assertEqual("FINALIZED", snapshot["status"])
                members = repository.connection.execute(
                    """SELECT ordinal, inclusion_reason_json
                    FROM dataset_members WHERE dataset_snapshot_id = ?
                    ORDER BY ordinal""",
                    (snapshot_id,),
                ).fetchall()
                self.assertEqual([0, 1], [row["ordinal"] for row in members])
                self.assertTrue(
                    all("post_url" not in row["inclusion_reason_json"] for row in members)
                )
                self.assertEqual(3, repository.count("browser_normalized_bridges"))

                analysis_batch_id = repository.create_analysis_batch(
                    "detail-delta-analysis", snapshot_id, CONFIG
                )
                analyzed = run_analysis_batch(
                    repository, analysis_batch_id, DeterministicMockAdapter()
                )
                self.assertEqual("SUCCEEDED", analyzed.status)
                self.assertEqual(2, analyzed.succeeded)

                structural_run_id = repository.create_structural_feature_run(
                    snapshot_id,
                    TAXONOMY_VERSION,
                    EXTRACTOR_VERSION,
                    {"source": "completed_detail_batch"},
                )
                self.assertEqual(
                    2, derive_structural_features(repository, structural_run_id)
                )
                self.assertEqual(2, repository.count("structural_feature_instances"))

    def test_requires_completed_batch_and_rejects_stale_non_detail_current_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with Repository(Path(directory) / "guard.sqlite3") as repository:
                repository.add_browser_observation(
                    browser_observation("Guard", "valid source", "SEARCH_CARD")
                )
                batch_id = repository.start_browser_detail_batch(
                    requested_items=1, max_items=1
                )
                with self.assertRaisesRegex(ValueError, "COMPLETED"):
                    prepare_detail_batch_analysis(
                        repository, batch_id, "running", 1
                    )
                complete_item(repository, batch_id, "Guard", "valid detail")
                repository.finish_browser_detail_batch(batch_id)
                repository.add_browser_observation(
                    browser_observation("Guard", "later search", "SEARCH_CARD")
                )
                result = prepare_detail_batch_analysis(
                    repository, batch_id, "stale", 1
                )
                self.assertEqual(0, result["valid_member_count"])
                self.assertEqual(1, result["excluded_count"])


if __name__ == "__main__":
    unittest.main()
