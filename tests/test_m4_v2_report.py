import unittest

from social_content_engine.intelligence.m4_v2_report import _aggregate, metric_coverage


class M4V2ReportTest(unittest.TestCase):
    def test_unknown_none_clusters_are_not_actionable_patterns(self) -> None:
        self.assertEqual([], _aggregate([{"labels": ["UNKNOWN"]}] * 3, "labels"))
        result = _aggregate([{"labels": ["QUESTION"]}] * 2, "labels")
        self.assertEqual(1, len(result))
        self.assertEqual(2, result[0]["support_count"])

    def test_metric_coverage_is_specific_and_missing_is_not_zero(self) -> None:
        coverage = metric_coverage([{"field_name": "public_counters.view_count"}])
        self.assertEqual(1, coverage["public_counters.view_count"]["observed_count"])
        self.assertEqual(
            "INSUFFICIENT_COVERAGE", coverage["public_counters.view_count"]["status"]
        )
        self.assertEqual(0, coverage["public_counters.like_count"]["observed_count"])


if __name__ == "__main__":
    unittest.main()
