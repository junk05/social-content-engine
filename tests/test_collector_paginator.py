import json
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List

from social_content_engine.collector.client import HttpCapture
from social_content_engine.collector.paginator import CollectionPlan, collect, summary_json


def capture(payload: Any, status: int = 200) -> HttpCapture:
    return HttpCapture(
        endpoint="/keyword_search",
        request_params={},
        started_at="start",
        completed_at="end",
        status=status,
        headers={},
        body=json.dumps(payload).encode("utf-8"),
    )


class FixtureFetch:
    def __init__(self, responses: List[HttpCapture]) -> None:
        self.responses = responses
        self.calls: List[Dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> HttpCapture:
        self.calls.append(kwargs)
        return self.responses.pop(0)


class CollectorPaginatorTest(unittest.TestCase):
    def plan(self, **overrides: Any) -> CollectionPlan:
        values: Dict[str, Any] = {
            "queries": ["alpha"],
            "search_types": ["RECENT"],
            "page_limit": 2,
            "target_unique": 10,
            "hard_cap": 20,
            "max_requests": 5,
            "live_interval_seconds": 2,
        }
        values.update(overrides)
        return CollectionPlan(**values)

    def test_two_pages_deduplicate_overlap_and_forward_opaque_cursor(self) -> None:
        fetch = FixtureFetch(
            [
                capture(
                    {
                        "data": [{"id": "1"}, {"id": "2"}],
                        "paging": {"cursors": {"after": "opaque/+="}},
                    }
                ),
                capture({"data": [{"id": "2"}, {"id": "3"}], "paging": {"cursors": {"after": ""}}}),
            ]
        )
        result = collect(self.plan(), fetch, sleep=lambda _: None)
        self.assertEqual(["1", "2", "3"], result["seen_ids"])
        self.assertEqual(4, result["observation_count"])
        self.assertEqual("opaque/+=", fetch.calls[1]["after"])
        self.assertEqual("KEYWORD", fetch.calls[0]["search_mode"])

    def test_repeated_cursor_stops_current_job(self) -> None:
        fetch = FixtureFetch(
            [
                capture({"data": [{"id": "1"}], "paging": {"cursors": {"after": "same"}}}),
                capture({"data": [{"id": "2"}], "paging": {"cursors": {"after": "same"}}}),
            ]
        )
        result = collect(self.plan(), fetch, sleep=lambda _: None)
        self.assertEqual("REPEATED_CURSOR", result["job_stops"][0]["reason"])
        self.assertEqual(2, result["request_count"])

    def test_empty_page_stops_without_following_cursor(self) -> None:
        fetch = FixtureFetch([capture({"data": [], "paging": {"cursors": {"after": "unused"}}})])
        result = collect(self.plan(), fetch, sleep=lambda _: None)
        self.assertEqual("EMPTY_PAGE", result["job_stops"][0]["reason"])
        self.assertEqual("PLAN_EXHAUSTED", result["stop_reason"])

    def test_target_hard_cap_and_request_cap(self) -> None:
        target = collect(
            self.plan(target_unique=2),
            FixtureFetch(
                [
                    capture(
                        {
                            "data": [{"id": "1"}, {"id": "2"}],
                            "paging": {"cursors": {"after": "next"}},
                        }
                    )
                ]
            ),
            sleep=lambda _: None,
        )
        self.assertEqual("TARGET_REACHED", target["stop_reason"])

        hard = collect(
            self.plan(target_unique=10, hard_cap=2),
            FixtureFetch(
                [
                    capture(
                        {
                            "data": [{"id": "1"}, {"id": "2"}, {"id": "3"}],
                            "paging": {"cursors": {"after": "next"}},
                        }
                    )
                ]
            ),
            sleep=lambda _: None,
        )
        self.assertEqual("HARD_CAP_REACHED", hard["stop_reason"])
        self.assertEqual(2, hard["unique_count"])

        capped = collect(
            self.plan(max_requests=1),
            FixtureFetch(
                [capture({"data": [{"id": "1"}], "paging": {"cursors": {"after": "next"}}})]
            ),
            sleep=lambda _: None,
        )
        self.assertEqual("REQUEST_CAP_REACHED", capped["stop_reason"])

    def test_resume_has_no_credential_and_summary_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            checkpoint = Path(directory) / "checkpoint.json"
            first = FixtureFetch([capture({"error": "temporary"}, status=503)])
            result1 = collect(self.plan(), first, checkpoint_path=checkpoint, sleep=lambda _: None)
            self.assertEqual("HTTP_ERROR", result1["stop_reason"])
            checkpoint_text = checkpoint.read_text(encoding="utf-8")
            self.assertNotIn("token", checkpoint_text.lower())

            second = FixtureFetch(
                [capture({"data": [{"id": "resumed"}], "paging": {"cursors": {"after": ""}}})]
            )
            result2 = collect(
                self.plan(), second, checkpoint_path=checkpoint, resume=True, sleep=lambda _: None
            )
            self.assertEqual(["resumed"], result2["seen_ids"])
            self.assertEqual(
                summary_json(result2), summary_json(dict(reversed(list(result2.items()))))
            )

    def test_malformed_data_and_paging_stop(self) -> None:
        for payload in (
            {"data": {}},
            {"data": [{"id": "1"}], "paging": []},
            {"data": [{"id": "1"}], "paging": {"cursors": []}},
        ):
            with self.subTest(payload=payload):
                result = collect(
                    self.plan(), FixtureFetch([capture(payload)]), sleep=lambda _: None
                )
                self.assertEqual("INVALID_RESPONSE", result["stop_reason"])

    def test_missing_or_empty_cursor_finishes_current_job(self) -> None:
        for payload in (
            {"data": [{"id": "1"}]},
            {"data": [{"id": "1"}], "paging": {"cursors": {"before": "x"}}},
            {"data": [{"id": "1"}], "paging": {"cursors": {"after": ""}}},
        ):
            with self.subTest(payload=payload):
                result = collect(
                    self.plan(), FixtureFetch([capture(payload)]), sleep=lambda _: None
                )
                self.assertEqual("NO_NEXT_CURSOR", result["job_stops"][0]["reason"])

    def test_multi_query_top_recent_plan_order_and_parameters(self) -> None:
        fetch = FixtureFetch(
            [capture({"data": [], "paging": {"cursors": {"after": ""}}}) for _ in range(4)]
        )
        plan = self.plan(
            queries=["a", "b"],
            search_types=["TOP", "RECENT"],
            search_mode="TAG",
            since="2026-01-01",
            until="2026-02-01",
        )
        collect(plan, fetch, sleep=lambda _: None)
        self.assertEqual(
            [("a", "TOP"), ("a", "RECENT"), ("b", "TOP"), ("b", "RECENT")],
            [(call["query"], call["search_type"]) for call in fetch.calls],
        )
        self.assertEqual("TAG", fetch.calls[0]["search_mode"])
        self.assertEqual("2026-01-01", fetch.calls[0]["since"])
        self.assertNotIn("access_token", fetch.calls[0])


if __name__ == "__main__":
    unittest.main()
