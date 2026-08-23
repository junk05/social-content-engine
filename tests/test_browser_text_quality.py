import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from social_content_engine.data.browser_observation import browser_observation_payload_sha256
from social_content_engine.data.browser_text_quality import (
    INVALID_TEXT_DATE_METADATA,
    INVALID_TEXT_REPLY_COMPOSER_METADATA,
    TEXT_UNAVAILABLE,
    VALID_TEXT,
    classify_browser_text_quality,
)
from social_content_engine.data.repository import Repository
from social_content_engine.intelligence.clean_dataset import (
    bridge_current_browser_roots,
    create_clean_browser_dataset_snapshot,
    create_clean_root_dataset_snapshot,
)
from tests.test_browser_observation_repository import observation


class BrowserTextQualityTest(unittest.TestCase):
    def test_classifies_only_observable_date_metadata_defect(self) -> None:
        self.assertEqual(INVALID_TEXT_DATE_METADATA, classify_browser_text_quality("2026/08/16"))
        self.assertEqual(INVALID_TEXT_DATE_METADATA, classify_browser_text_quality("3日"))
        self.assertEqual(TEXT_UNAVAILABLE, classify_browser_text_quality(None))
        self.assertEqual(VALID_TEXT, classify_browser_text_quality("短文でも本文です"))

    def test_assessment_is_append_only_and_does_not_mutate_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with Repository(Path(directory) / "quality.sqlite3") as repository:
                repository.connection.execute(
                    """INSERT INTO browser_post_identities
                    (source, post_url, status, created_at, updated_at)
                    VALUES ('threads', 'https://www.threads.net/@a/post/one', 'COLLECTED',
                            '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')"""
                )
                repository.connection.execute(
                    """INSERT INTO browser_observations
                    (browser_post_identity_id, observation_type, source, post_url, status,
                     canonical_payload_json, payload_sha256, field_provenance_json,
                     field_provenance_sha256, collection_context_json, collected_at,
                     extractor_version)
                    VALUES (1, 'SEARCH_CARD', 'threads', 'https://www.threads.net/@a/post/one',
                     'COLLECTED', ?, ?, '{}', ?, '{}', '2026-01-01T00:00:00Z', 'test-v1')""",
                    (json.dumps({"text": "2026/08/16"}), "a" * 64, "b" * 64),
                )
                repository.connection.commit()
                assessment_id = repository.assess_browser_text_quality(
                    browser_observation_id=1, quality_status=INVALID_TEXT_DATE_METADATA,
                    input_sha256=hashlib.sha256(b"input").hexdigest(),
                )
                self.assertEqual(1, assessment_id)
                reply_composer_assessment_id = repository.assess_browser_text_quality(
                    browser_observation_id=1,
                    quality_status=INVALID_TEXT_REPLY_COMPOSER_METADATA,
                    input_sha256=hashlib.sha256(b"reply-composer-input").hexdigest(),
                )
                self.assertEqual(2, reply_composer_assessment_id)
                self.assertEqual(1, repository.count("browser_observations"))
                with self.assertRaises(Exception):
                    repository.connection.execute(
                        "UPDATE browser_text_quality_assessments SET quality_status = 'VALID_TEXT'"
                    )

    def test_clean_snapshot_excludes_metadata_without_invalidating_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with Repository(Path(directory) / "clean.sqlite3") as repository:
                valid_payload = observation(text="質問ですか？")
                valid_payload["post_url"] = "https://www.threads.net/@valid/post/one"
                valid_payload["payload_sha256"] = browser_observation_payload_sha256(valid_payload)
                valid = repository.add_browser_observation(valid_payload)
                invalid_payload = observation(text="3日")
                invalid_payload["post_url"] = "https://www.threads.net/@invalid/post/two"
                invalid_payload["payload_sha256"] = browser_observation_payload_sha256(
                    invalid_payload
                )
                invalid = repository.add_browser_observation(invalid_payload)
                repository.bridge_browser_post(valid["post_url"])
                repository.bridge_browser_post(invalid["post_url"])
                result = create_clean_browser_dataset_snapshot(
                    repository, dataset_key="m4-clean-fixture", version=1
                )
                self.assertEqual(1, result["member_count"])
                member = repository.connection.execute(
                    "SELECT selected_browser_observation_id FROM dataset_members"
                ).fetchone()
                self.assertEqual(valid["browser_observation_id"], member[0])
                quality = repository.connection.execute(
                    """SELECT quality_status FROM browser_text_quality_assessments
                    WHERE browser_observation_id = ?""",
                    (invalid["browser_observation_id"],),
                ).fetchone()
                self.assertEqual(INVALID_TEXT_DATE_METADATA, quality[0])
                self.assertEqual(2, repository.count("browser_post_identities"))

    def test_root_snapshot_excludes_child_only_identity_and_reports_quality(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with Repository(Path(directory) / "root-clean.sqlite3") as repository:
                root_payload = observation(text="有効な親投稿です")
                root_payload["post_url"] = "https://www.threads.net/@valid/post/root"
                root_payload["payload_sha256"] = browser_observation_payload_sha256(
                    root_payload
                )
                repository.add_browser_observation(root_payload)
                invalid_payload = observation(text="3日")
                invalid_payload["post_url"] = "https://www.threads.net/@invalid/post/root"
                invalid_payload["payload_sha256"] = browser_observation_payload_sha256(
                    invalid_payload
                )
                repository.add_browser_observation(invalid_payload)
                child_payload = observation(text="子投稿", observation_type="POST_DETAIL")
                child_payload["post_url"] = "https://www.threads.net/@valid/post/child"
                child_payload["payload_sha256"] = browser_observation_payload_sha256(
                    child_payload
                )
                child = repository.add_browser_observation(child_payload)
                self.assertEqual(2, bridge_current_browser_roots(repository))
                repository.bridge_browser_post(child["post_url"])

                result = create_clean_root_dataset_snapshot(
                    repository, dataset_key="m4-root-clean", version=1
                )
                self.assertEqual(2, result["canonical_root_count"])
                self.assertEqual(1, result["member_count"])
                self.assertEqual(1, result["excluded_count"])
                self.assertEqual(
                    {"INVALID_TEXT_DATE_METADATA": 1}, result["quality_exclusions"]
                )


if __name__ == "__main__":
    unittest.main()
