import unittest

from social_content_engine.data.normalize import normalize_threads_post


class NormalizeTest(unittest.TestCase):
    def test_missing_id_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            normalize_threads_post({}, "0" * 64)

    def test_unknown_fields_are_not_invented(self) -> None:
        result = normalize_threads_post(
            {"id": "1"}, "0" * 64, normalized_at="2026-08-15T00:00:00+00:00"
        )
        self.assertIsNone(result["username"])
        self.assertIsNone(result["text"])


if __name__ == "__main__":
    unittest.main()
