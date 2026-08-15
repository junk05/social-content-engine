import io
import unittest
import urllib.error
from email.message import Message
from unittest.mock import patch

from social_content_engine.collector.client import ThreadsClient


class FakeResponse:
    def __init__(self, body: bytes = b'{"data": []}') -> None:
        self.status = 200
        self.headers = Message()
        self.headers["Content-Type"] = "application/json"
        self.body = body

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return self.body


class ClientTest(unittest.TestCase):
    @patch("social_content_engine.collector.client.urllib.request.urlopen")
    def test_token_is_sent_but_not_returned_in_provenance(self, urlopen: object) -> None:
        setattr(urlopen, "return_value", FakeResponse())
        capture = ThreadsClient("very-secret-token").keyword_search(
            query="恋愛",
            search_type="RECENT",
            fields="id,text",
            limit=1,
            search_mode="TAG",
            since="2026-01-01",
            until="2026-02-01",
        )
        request = getattr(urlopen, "call_args").args[0]
        self.assertIn("access_token=very-secret-token", request.full_url)
        self.assertNotIn("access_token", capture.request_params)
        self.assertNotIn("very-secret-token", repr(capture))
        self.assertEqual("TAG", capture.request_params["search_mode"])
        self.assertEqual("2026-01-01", capture.request_params["since"])
        self.assertEqual("2026-02-01", capture.request_params["until"])

    def test_keyword_search_guards_documented_local_bounds(self) -> None:
        client = ThreadsClient("token")
        with self.assertRaises(ValueError):
            client.keyword_search(query="q", search_type="RECENT", fields="id", limit=51)
        with self.assertRaises(ValueError):
            client.keyword_search(
                query="q", search_type="RECENT", fields="id", limit=1, search_mode="INVALID"
            )

    @patch("social_content_engine.collector.client.time.sleep")
    @patch("social_content_engine.collector.client.urllib.request.urlopen")
    def test_retries_429_with_bound(self, urlopen: object, sleep: object) -> None:
        headers = Message()
        headers["Retry-After"] = "99"
        error = urllib.error.HTTPError(
            "https://graph.threads.net/keyword_search",
            429,
            "rate limited",
            headers,
            io.BytesIO(b'{"error": "rate limited"}'),
        )
        setattr(urlopen, "side_effect", [error, FakeResponse()])
        capture = ThreadsClient("token", max_retries=1).keyword_search(
            query="test", search_type="TOP", fields="id", limit=1
        )
        self.assertEqual(200, capture.status)
        getattr(sleep, "assert_called_once_with")(30)


if __name__ == "__main__":
    unittest.main()
