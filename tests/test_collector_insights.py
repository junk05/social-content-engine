import json
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict

from social_content_engine.collector.client import HttpCapture
from social_content_engine.collector.insights import run_insights_spike
from social_content_engine.data.repository import Repository

THREAD_ID = "public-thread-1"


class FixtureInsights:
    def __init__(self, body: bytes, status: int = 200) -> None:
        self.capture = HttpCapture(
            endpoint="/public-thread-1/insights",
            request_params={"metric": "views,likes,replies,reposts,quotes,shares"},
            started_at="2026-08-16T00:00:00+00:00",
            completed_at="2026-08-16T00:00:01+00:00",
            status=status,
            headers={"content-type": "application/json"},
            body=body,
        )
        self.call: Dict[str, Any] = {}

    def __call__(self, **kwargs: Any) -> HttpCapture:
        self.call = kwargs
        return self.capture


def seed_post(repository: Repository) -> None:
    repository.upsert_normalized_post(
        {
            "source": "threads", "source_post_id": THREAD_ID, "author_id": "author",
            "username": "user", "text": "post", "permalink": "https://example.test/post",
            "published_at": "2026-08-16T00:00:00+00:00", "media_type": "TEXT_POST",
            "raw_sha256": "a" * 64, "normalized_at": "2026-08-16T00:00:00+00:00",
        }
    )


class CollectorInsightsTest(unittest.TestCase):
    def test_exact_raw_capture_zero_and_only_explicit_metrics(self) -> None:
        body = json.dumps(
            {
                "data": [
                    {"name": "views", "values": [{"value": 0}]},
                    {"name": "likes", "total_value": {"value": 7}},
                    {"name": "replies"},
                    {"name": "quotes", "total_value": {"value": None}},
                    {"name": "invented", "total_value": {"value": 999}},
                ]
            },
            separators=(",", ":"),
        ).encode("utf-8")
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "test.sqlite3"
            raw_dir = Path(directory) / "raw"
            with Repository(database) as repository:
                seed_post(repository)
                fixture = FixtureInsights(body)
                result = run_insights_spike(
                    repository=repository, fetch=fixture, thread_id=THREAD_ID,
                    raw_dir=raw_dir, collector_version="fixture",
                )
                run = repository.connection.execute(
                    "SELECT request_json, raw_response FROM collection_runs WHERE id = ?",
                    (result["collection_run_id"],),
                ).fetchone()
                rows = repository.connection.execute(
                    """SELECT metric_name, metric_value FROM post_metric_observations
                    ORDER BY metric_name"""
                ).fetchall()
            self.assertEqual(body, bytes(run["raw_response"]))
            self.assertNotIn("token", str(run["request_json"]).lower())
            self.assertEqual([("likes", 7), ("views", 0)], [(r[0], r[1]) for r in rows])
            self.assertEqual(["likes", "views"], result["stored_metrics"])
            self.assertEqual(["quotes", "replies", "reposts", "shares"], result["unknown_metrics"])
            self.assertEqual(body, Path(result["raw_path"]).read_bytes())
            self.assertEqual(
                "views,likes,replies,reposts,quotes,shares", fixture.call["metrics"]
            )

    def test_403_is_raw_evidence_and_creates_no_metric_rows(self) -> None:
        body = b'{"error":{"message":"Unsupported get request","code":100}}'
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "test.sqlite3"
            with Repository(database) as repository:
                seed_post(repository)
                result = run_insights_spike(
                    repository=repository, fetch=FixtureInsights(body, 403),
                    thread_id=THREAD_ID, raw_dir=Path(directory) / "raw",
                )
                run = repository.connection.execute(
                    "SELECT http_status, raw_response FROM collection_runs"
                ).fetchone()
                count = repository.count("post_metric_observations")
            self.assertEqual(403, result["http_status"])
            self.assertEqual((403, body), (run["http_status"], bytes(run["raw_response"])))
            self.assertEqual(0, count)
            self.assertEqual([], result["stored_metrics"])


if __name__ == "__main__":
    unittest.main()
