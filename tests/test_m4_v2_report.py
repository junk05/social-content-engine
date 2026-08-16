import unittest

from social_content_engine.intelligence.m4_v2_report import (
    REPORT_VERSION,
    _aggregate,
    metric_coverage,
)


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

    def test_short_form_patterns_are_actionable_when_supported(self) -> None:
        patterns = _aggregate(
            [{"labels": ["STANDALONE_SHORT"]}] * 2, "labels"
        )
        self.assertEqual("STANDALONE_SHORT", patterns[0]["mechanism"][0])

    def test_report_version_is_revised(self) -> None:
        self.assertEqual("M4_V2_VIRAL_PATTERN_REPORT_V2", REPORT_VERSION)

    def test_first_line_aggregation_keeps_multilabel_dimensions(
        self,
    ) -> None:
        generic = {"signature": {
            "rhetorical": ["ASSERTION"], "audience_tension": [],
            "continuation": ["NONE"], "certainty": "UNKNOWN",
        }}
        useful = {"signature": {
            "rhetorical": ["QUESTION"], "audience_tension": ["READER_TARGETING"],
            "continuation": ["CURIOSITY_GAP"], "certainty": "AMBIGUOUS",
        }}
        result = _aggregate([generic, generic, useful, useful], "signature")
        self.assertEqual(1, len(result))
        self.assertEqual(2, result[0]["support_count"])
        self.assertEqual("CONTINUE_READING_HYPOTHESIS", result[0]["expected_psychological_effect"])
        self.assertIn("READER_TARGETING", result[0]["abstract_formula"])


if __name__ == "__main__":
    unittest.main()
