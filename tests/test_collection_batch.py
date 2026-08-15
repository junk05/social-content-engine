import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any, List

from social_content_engine.collector.batch import build_parser, run_collection_batch
from social_content_engine.collector.client import HttpCapture
from social_content_engine.collector.paginator import CollectionPlan
from social_content_engine.data.repository import Repository


class FixtureClient:
    def __init__(self, payloads: List[dict]) -> None:
        self.payloads = payloads

    def keyword_search(self, **params: Any) -> HttpCapture:
        return HttpCapture(
            endpoint="/keyword_search",
            request_params={key: str(value) for key, value in params.items()},
            started_at="2026-08-16T00:00:00+00:00",
            completed_at="2026-08-16T00:00:01+00:00",
            status=200,
            headers={"content-type": "application/json"},
            body=json.dumps(self.payloads.pop(0)).encode("utf-8"),
        )


class CollectionBatchTest(unittest.TestCase):
    def test_cli_can_bound_canary_to_one_search_type(self) -> None:
        args = build_parser().parse_args(
            ["--query", "恋愛", "--search-type", "TOP", "--max-requests", "1"]
        )
        self.assertEqual(["恋愛"], args.queries)
        self.assertEqual(["TOP"], args.search_types)

    def test_each_page_preserves_exact_capture_batch_link_and_versions(self) -> None:
        payloads = [
            {"data": [{"id": "1", "text": "one"}], "paging": {"cursors": {"after": "n"}}},
            {"data": [{"id": "2", "text": "two"}], "paging": {"cursors": {"after": ""}}},
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with Repository(root / "test.sqlite3") as repository:
                result = run_collection_batch(
                    repository,
                    FixtureClient(payloads),  # type: ignore[arg-type]
                    CollectionPlan(
                        queries=("fixture",),
                        search_types=("RECENT",),
                        page_limit=1,
                        target_unique=10,
                        hard_cap=20,
                        max_requests=2,
                        live_interval_seconds=2,
                    ),
                    batch_key="fixture-batch",
                    raw_dir=root / "raw",
                )
                self.assertEqual(2, result["unique_count"])
                self.assertEqual(2, repository.count("collection_runs"))
                self.assertEqual(2, repository.count("collection_batch_runs"))
                self.assertEqual(2, repository.count("normalized_post_versions"))
                rows = repository.connection.execute(
                    "SELECT raw_response, raw_response_sha256 FROM collection_runs ORDER BY id"
                ).fetchall()
                for row in rows:
                    self.assertEqual(
                        hashlib.sha256(bytes(row["raw_response"])).hexdigest(),
                        row["raw_response_sha256"],
                    )
                self.assertEqual(2, len(list((root / "raw").glob("*.json"))))

    def test_malformed_success_is_retained_and_batch_fails_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            client = FixtureClient([])
            client.keyword_search = lambda **_params: HttpCapture(
                "/keyword_search", {}, "start", "end", 200, {}, b"not-json"
            )
            with Repository(root / "test.sqlite3") as repository:
                result = run_collection_batch(
                    repository,
                    client,  # type: ignore[arg-type]
                    CollectionPlan(
                        queries=("fixture",), max_requests=1, live_interval_seconds=2
                    ),
                    batch_key="malformed-batch",
                    raw_dir=root / "raw",
                )
                self.assertEqual("INVALID_RESPONSE", result["stop_reason"])
                status = repository.connection.execute(
                    "SELECT status FROM collection_batches"
                ).fetchone()[0]
                self.assertEqual("FAILED", status)
                self.assertEqual(1, repository.count("collection_runs"))


if __name__ == "__main__":
    unittest.main()
