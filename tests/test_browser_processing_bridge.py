import tempfile
import unittest
from pathlib import Path

from social_content_engine.analyzer.batch import run_analysis_batch
from social_content_engine.analyzer.contracts import TAXONOMY_VERSION
from social_content_engine.analyzer.mock_adapter import DeterministicMockAdapter
from social_content_engine.analyzer.orchestrator import (
    ANALYZER_VERSION,
    MODEL_NAME,
    MODEL_PARAMETERS,
    MODEL_PROVIDER,
    PROMPT_VERSION,
)
from social_content_engine.data.repository import Repository
from social_content_engine.intelligence.first_line import (
    EXTRACTOR_VERSION as FIRST_EXTRACTOR_VERSION,
)
from social_content_engine.intelligence.first_line import extract_first_line
from social_content_engine.intelligence.parent_ending import (
    EXTRACTOR_VERSION as ENDING_EXTRACTOR_VERSION,
)
from social_content_engine.intelligence.parent_ending import extract_parent_ending
from social_content_engine.intelligence.pattern_miner import mine_patterns
from tests.test_browser_observation_repository import observation

CONFIG = {
    "analyzer_version": ANALYZER_VERSION,
    "taxonomy_version": TAXONOMY_VERSION,
    "prompt_version": PROMPT_VERSION,
    "model_provider": MODEL_PROVIDER,
    "model_name": MODEL_NAME,
    "model_parameters": MODEL_PARAMETERS,
}


class BrowserProcessingBridgeTest(unittest.TestCase):
    def test_bridge_is_versioned_idempotent_and_runs_existing_m1_m2_pipeline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with Repository(Path(directory) / "test.sqlite3") as repository:
                first_capture = repository.add_browser_observation(observation(text="質問？"))
                first = repository.bridge_browser_post(first_capture["post_url"])
                replay = repository.bridge_browser_post(first_capture["post_url"])
                self.assertEqual(
                    first["normalized_post_version_id"], replay["normalized_post_version_id"]
                )
                self.assertEqual(1, repository.count("browser_normalized_bridges"))

                repository.add_browser_observation(observation(text="変更後の質問？"))
                changed = repository.bridge_browser_post(first_capture["post_url"])
                self.assertEqual(2, changed["normalized_post_version"])
                self.assertEqual(2, repository.count("browser_normalized_bridges"))
                self.assertEqual(1, repository.count("normalized_posts"))
                normalized = repository.get_normalized_post(
                    first_capture["post_url"], source="threads_browser"
                )
                self.assertIsNone(normalized["author_id"])
                self.assertEqual("変更後の質問？", normalized["text"])
                self.assertEqual(first_capture["post_url"], normalized["permalink"])
                self.assertEqual(0, repository.count("raw_posts"))

                snapshot_id = repository.create_dataset_snapshot(
                    "browser-fixture", 1, {"source": "threads_browser"}
                )
                repository.add_browser_dataset_member(
                    snapshot_id,
                    changed["normalized_post_version_id"],
                    changed["source_browser_observation_id"],
                    0,
                    {"reason": "explicit_browser_bridge"},
                )
                repository.finalize_dataset_snapshot(snapshot_id)
                batch_id = repository.create_analysis_batch(
                    "browser-fixture", snapshot_id, CONFIG
                )
                batch = run_analysis_batch(
                    repository, batch_id, DeterministicMockAdapter()
                )
                self.assertEqual("SUCCEEDED", batch.status)
                run = repository.connection.execute(
                    "SELECT id FROM analysis_runs WHERE normalized_post_version_id = ?",
                    (changed["normalized_post_version_id"],),
                ).fetchone()
                self.assertIsNotNone(run)
                run_id = int(run["id"])
                extract_first_line(repository, run_id)
                ending = extract_parent_ending(repository, run_id)
                self.assertEqual("NO_PARENT", ending["feature"]["availability"])
                mined = mine_patterns(
                    repository,
                    dataset_snapshot_id=snapshot_id,
                    analyzer_version=ANALYZER_VERSION,
                    taxonomy_version=TAXONOMY_VERSION,
                    prompt_version=PROMPT_VERSION,
                    model_provider=MODEL_PROVIDER,
                    model_name=MODEL_NAME,
                    model_parameters=MODEL_PARAMETERS,
                    first_line_extractor_version=FIRST_EXTRACTOR_VERSION,
                    parent_ending_extractor_version=ENDING_EXTRACTOR_VERSION,
                )
                self.assertEqual(1, mined["selected_instance_count"])
                self.assertEqual(1, len(mined["singletons"]))


if __name__ == "__main__":
    unittest.main()
