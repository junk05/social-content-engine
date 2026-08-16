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
            "top_first_line_component_patterns": [{
                "abstract_formula": "TARGET_READER -> QUESTION", "support_count": 2,
                "evidence_count": 2, "distinct_source_count": 2, "confidence": "LOW",
                "performance_statistics": {},
            }],
            "top_post_structure_patterns": [], "observed_thread_structure_patterns": [],
        }
        rendered = render_structural_pattern_report(report)
        self.assertIn("TARGET_READER -> QUESTION", rendered)
        self.assertIn("INSUFFICIENT_EVIDENCE", rendered)
        self.assertNotIn("https://", rendered)
        self.assertNotIn("source_post_id", rendered)


if __name__ == "__main__":
    unittest.main()
