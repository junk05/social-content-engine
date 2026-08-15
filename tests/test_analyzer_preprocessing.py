import copy
import hashlib
import unittest

from social_content_engine.analyzer.preprocessing import (
    build_analyzer_input,
    canonical_json_bytes,
    input_sha256,
)


class AnalyzerPreprocessingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.post = {
            "schema_version": 1,
            "source": "threads",
            "source_post_id": "post-1",
            "author_id": "account-1",
            "username": "fixture",
            "text": "Cafe\u0301へ。\nhttps://example.test #相談 @friend 😊！？?！",
            "permalink": "https://threads.test/post-1",
            "published_at": "2026-08-16T00:00:00+00:00",
            "media_type": "TEXT_POST",
            "raw_sha256": "0" * 64,
            "normalized_at": "2026-08-16T00:01:00+00:00",
        }

    def test_builds_observation_only_input_and_features(self) -> None:
        result = build_analyzer_input(self.post)
        self.assertEqual("Caféへ。", result["text"].splitlines()[0])
        self.assertEqual("account-1", result["author_id"])
        self.assertIsNone(result["language_hint"])
        self.assertEqual({}, result["public_metrics"])
        self.assertEqual(
            {
                "character_count": 45,
                "line_count": 2,
                "url_count": 1,
                "hashtag_count": 1,
                "mention_count": 1,
                "emoji_count": 1,
                "question_mark_count": 2,
                "exclamation_mark_count": 2,
            },
            result["text_features"],
        )
        self.assertNotIn("sentiment", result)
        self.assertNotIn("topic", result)

    def test_canonical_serialization_and_hash_ignore_mapping_order(self) -> None:
        first = build_analyzer_input(self.post)
        second = dict(reversed(list(copy.deepcopy(first).items())))
        self.assertEqual(canonical_json_bytes(first), canonical_json_bytes(second))
        expected_hash = hashlib.sha256(canonical_json_bytes(first)).hexdigest()
        self.assertEqual(expected_hash, input_sha256(first))

    def test_empty_text_is_supported_without_inference(self) -> None:
        post = dict(self.post, text=None)
        result = build_analyzer_input(post)
        self.assertEqual("", result["text"])
        self.assertEqual(0, result["text_features"]["line_count"])

    def test_requires_normalized_identity(self) -> None:
        with self.assertRaises(ValueError):
            build_analyzer_input({"source": "threads", "text": "missing id"})


if __name__ == "__main__":
    unittest.main()
