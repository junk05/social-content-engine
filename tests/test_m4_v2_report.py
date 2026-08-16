import unittest

from social_content_engine.intelligence.m4_v2_report import (
    REPORT_VERSION,
    _aggregate,
    first_line_coverage,
    metric_coverage,
    render_v2_pattern_report,
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
        self.assertEqual("M4_V2_VIRAL_PATTERN_REPORT_V3", REPORT_VERSION)

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
        self.assertEqual(
            "PSYCHOLOGY_HYPOTHESIS",
            result[0]["psychology_hypotheses"][0]["evidence_mode"],
        )
        self.assertIn("INFORMATION_GAP", str(result[0]["psychology_hypotheses"]))
        self.assertIn("READER_TARGETING", result[0]["abstract_formula"])

    def test_first_line_funnel_distinguishes_generic_singleton_and_promoted(self) -> None:
        generic = {"first_line": {
            "availability": "OBSERVED", "rhetorical_mechanisms": ["ASSERTION"],
            "audience_tension_mechanisms": [], "continuation_mechanisms": ["NONE"],
            "certainty_level": "UNKNOWN",
        }}
        promoted = {"first_line": {
            "availability": "OBSERVED", "rhetorical_mechanisms": ["QUESTION"],
            "audience_tension_mechanisms": ["READER_TARGETING"],
            "continuation_mechanisms": ["CURIOSITY_GAP"], "certainty_level": "AMBIGUOUS",
        }}
        singleton = {"first_line": {
            "availability": "OBSERVED", "rhetorical_mechanisms": ["WARNING"],
            "audience_tension_mechanisms": [], "continuation_mechanisms": ["NONE"],
            "certainty_level": "CERTAIN",
        }}
        empty = {"first_line": {
            "availability": "EMPTY", "rhetorical_mechanisms": [],
            "audience_tension_mechanisms": [], "continuation_mechanisms": ["NONE"],
            "certainty_level": "UNKNOWN",
        }}
        coverage = first_line_coverage([generic, promoted, promoted, singleton, empty])
        funnel = coverage["funnel"]
        self.assertEqual(5, funnel["analyzed_posts"])
        self.assertEqual(4, funnel["first_line_available"])
        self.assertEqual(1, funnel["no_meaningful_feature_detected"])
        self.assertEqual(3, funnel["pattern_candidate"])
        self.assertEqual(1, funnel["singleton_candidate"])
        self.assertEqual(2, funnel["support_gte_2"])
        self.assertEqual(1, funnel["promoted_pattern"])
        self.assertEqual(2, coverage["feature_frequency"]["rhetorical"]["QUESTION"])

    def test_markdown_report_is_human_readable_and_has_no_source_identifiers(self) -> None:
        report = {
            "report_version": REPORT_VERSION,
            "run_id": 1,
            "top_first_line_patterns": [{
                "abstract_formula": "RHETORICAL:[\"QUESTION\"]",
                "support_count": 2, "evidence_count": 2, "confidence": "LOW",
                "psychology_hypotheses": [{"evidence_mode": "PSYCHOLOGY_HYPOTHESIS"}],
            }],
            "top_body_patterns": [], "top_open_loop_patterns": [],
            "top_action_patterns": [], "top_thread_form_patterns": [],
            "metric_coverage": {"public_counters.view_count": {
                "observed_count": 1, "status": "INSUFFICIENT_COVERAGE",
            }},
            "metric_collection_audit": {"public_counters.view_count": {
                "observed_count": 1, "observation_count": 1,
                "status": "OBSERVED_BY_BROWSER_COLLECTOR",
            }},
            "first_line_coverage": {"funnel": {"analyzed_posts": 1},
                "feature_frequency": {"rhetorical": {}}, "definitions": {}},
        }
        rendered = render_v2_pattern_report(report)
        self.assertIn("# VIRAL PATTERN REPORT", rendered)
        self.assertIn("Support / evidence: 2 / 2", rendered)
        self.assertNotIn("https://", rendered)
        self.assertNotIn("username", rendered.lower())


if __name__ == "__main__":
    unittest.main()
