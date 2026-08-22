import unittest

from social_content_engine.intelligence.structural_report import (
    REPORT_VERSION,
    render_structural_pattern_report,
)


class StructuralReportTest(unittest.TestCase):
    def test_report_is_human_readable_and_has_no_source_identifiers(self) -> None:
        report = {
            "report_version": REPORT_VERSION, "structural_feature_run_id": 1,
            "dataset_snapshot_id": 1, "source_text_stored": False,
            "coverage": {"instances": 2, "first_line_unavailable": 0},
            "dataset_selection": {"contract_version": "m4-clean-browser-text-v1"},
            "selected_text_quality": {"VALID_TEXT": 2},
            "approximate_views_semantics": {
                "use": "DESCRIPTIVE_BAND_DISTRIBUTION_ONLY",
                "precision": "ROUNDED",
                "exact_ranking": False,
                "causal_inference": False,
                "missing_is_zero": False,
            },
            "top_first_line_component_patterns": [{
                "abstract_formula": "TARGET_READER -> QUESTION", "support_count": 2,
                "component_sequence": ["TARGET_READER", "QUESTION"],
                "evidence_count": 2, "distinct_source_count": 2, "confidence": "LOW",
                "performance_statistics": {
                    "approximate_views_observed": 2,
                    "approximate_views_band_10K_100K": 2,
                },
            }],
            "top_post_structure_patterns": [], "observed_thread_structure_patterns": [],
        }
        rendered = render_structural_pattern_report(report)
        self.assertIn("TARGET_READER -> QUESTION", rendered)
        self.assertIn("VALID_TEXT: 2", rendered)
        self.assertIn("DESCRIPTIVE_BAND_DISTRIBUTION_ONLY", rendered)
        self.assertIn('"approximate_views_band_10K_100K": 2', rendered)
        self.assertIn("INSUFFICIENT_EVIDENCE", rendered)
        self.assertNotIn("https://", rendered)
        self.assertNotIn("source_post_id", rendered)

    def test_report_renders_readiness_and_comparison_without_claiming_causality(self) -> None:
        report = {
            "report_version": REPORT_VERSION,
            "structural_feature_run_id": 2,
            "coverage": {"instances": 120, "rounded_views_observed": 60},
            "dataset_selection": {},
            "selected_text_quality": {"VALID_TEXT": 120},
            "approximate_views_semantics": {
                "use": "DESCRIPTIVE_BAND_DISTRIBUTION_ONLY",
                "precision": "ROUNDED",
                "view_band_distribution": {"100K_1M": 4},
            },
            "top_first_line_component_patterns": [],
            "top_post_structure_patterns": [],
            "observed_thread_structure_patterns": [],
            "removed_or_below_support_patterns": [{
                "pattern_kind": "FIRST_LINE",
                "component_sequence": ["QUESTION"],
                "previous_support": 2,
            }],
            "thread_length_distribution": {"4": 1},
            "pattern_library_readiness": {
                "status": "READY_WITH_LIMITATIONS",
                "limitations": ["ROUNDED_VIEWS_COVERAGE_BELOW_70_PERCENT"],
            },
        }
        rendered = render_structural_pattern_report(report)
        self.assertIn("READY_WITH_LIMITATIONS", rendered)
        self.assertIn("4 nodes: 1 roots", rendered)
        self.assertIn("Pattern frequency is not performance superiority", rendered)
        self.assertIn("M5 start authorized: false", rendered)


if __name__ == "__main__":
    unittest.main()
