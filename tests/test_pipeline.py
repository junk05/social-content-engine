import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from social_content_engine.data.pipeline import ingest_response
from social_content_engine.data.repository import Repository

FIXTURE = Path(__file__).parent / "fixtures" / "threads_keyword_search.json"
LIVE_SANITIZED_FIXTURE = (
    Path(__file__).parent / "fixtures" / "threads_keyword_search_live_sanitized.json"
)


class PipelineTest(unittest.TestCase):
    def test_fixture_is_normalized_and_deduplicated(self) -> None:
        raw = FIXTURE.read_bytes()
        with tempfile.TemporaryDirectory() as directory:
            with Repository(Path(directory) / "test.sqlite3") as repository:
                kwargs = {
                    "endpoint": "/keyword_search",
                    "request": {"params": {"q": "fixture", "search_type": "RECENT"}},
                    "started_at": "2026-08-15T00:00:00+00:00",
                    "completed_at": "2026-08-15T00:00:01+00:00",
                    "http_status": 200,
                    "response_headers": {"content-type": "application/json"},
                    "raw_response": raw,
                    "collector_version": "test",
                }
                first = ingest_response(repository, **kwargs)
                second = ingest_response(repository, **kwargs)
                self.assertEqual("fixture-thread-001", first[0]["source_post_id"])
                self.assertEqual(first, second)
                self.assertEqual(2, repository.count("raw_posts"))
                self.assertEqual(1, repository.count("normalized_posts"))
                self.assertEqual(2, repository.count("collection_runs"))
                rows = repository.connection.execute(
                    "SELECT raw_response, raw_response_sha256 FROM collection_runs ORDER BY id"
                ).fetchall()
                expected_hash = hashlib.sha256(raw).hexdigest()
                for row in rows:
                    self.assertEqual(raw, bytes(row["raw_response"]))
                    self.assertEqual(expected_hash, row["raw_response_sha256"])

    def test_fixture_is_valid_json_object(self) -> None:
        payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.assertIsInstance(payload["data"], list)

    def test_sanitized_live_fixture_preserves_observed_shape(self) -> None:
        payload = json.loads(LIVE_SANITIZED_FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(
            {"id", "media_type", "owner", "permalink", "text", "timestamp", "username"},
            set(payload["data"][0]),
        )
        self.assertEqual({"after", "before"}, set(payload["paging"]["cursors"]))
        serialized = json.dumps(payload)
        self.assertNotIn("SCEM0VERIFY20260816", serialized)


if __name__ == "__main__":
    unittest.main()
