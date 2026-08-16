import unittest

from social_content_engine.intelligence.m4_intelligence import (
    build_intelligence_feature,
    sequence_signature,
)


class M4IntelligenceTest(unittest.TestCase):
    def test_derives_closed_mechanisms_without_source_text(self) -> None:
        feature = build_intelligence_feature(
            {"hook_family": "QUESTION", "hook_subtype": "WHY_QUESTION", "read_more_pressure": 2,
             "expected_action": "CONTINUE_READING", "m1_action_labels": ["ASK"],
             "m1_structure_labels": ["QUESTION_LED", "OPEN_LOOP"]},
            {"availability": "NO_PARENT", "open_loop_score": "UNKNOWN", "closure_score": "UNKNOWN",
             "cliffhanger_technique": "UNKNOWN"},
        )
        self.assertEqual(
            ["QUESTION_GAP", "WITHHELD_REASON"],
            feature["hook"]["continue_reading_mechanisms"],
        )
        self.assertEqual(
            ["CONTINUE_READING", "REPLY_OR_COMMENT"], feature["expected_reader_actions"]
        )
        self.assertEqual("HYPOTHESIS", feature["action_evidence_mode"])
        self.assertNotIn("text", str(feature).lower())
        signature = sequence_signature(feature)
        self.assertEqual("QUESTION", signature["hook_family"])
        self.assertNotIn("text", str(signature).lower())


if __name__ == "__main__":
    unittest.main()
