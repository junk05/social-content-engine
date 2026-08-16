import unittest

from social_content_engine.intelligence.m4_v2_report import _aggregate


class M4V2ReportTest(unittest.TestCase):
    def test_unknown_none_clusters_are_not_actionable_patterns(self) -> None:
        self.assertEqual([], _aggregate([{"labels": ["UNKNOWN"]}] * 3, "labels"))
        result = _aggregate([{"labels": ["QUESTION"]}] * 2, "labels")
        self.assertEqual(1, len(result))
        self.assertEqual(2, result[0]["support_count"])


if __name__ == "__main__":
    unittest.main()
