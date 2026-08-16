import unittest

from social_content_engine.intelligence.m4_v2 import build_v2_feature


class M4V2Test(unittest.TestCase):
    def test_multi_label_first_line_and_text_free_evidence(self) -> None:
        feature = build_v2_feature(
            "恋愛で後悔したくない女性へ。実は、今すぐ知るべき3つの理由",
            {"availability": "NO_PARENT", "cliffhanger_technique": "UNKNOWN"},
        )
        labels = feature["first_line"]["rhetorical_mechanisms"]
        self.assertIn("REVELATION", labels)
        self.assertIn("NUMBER_LIST", labels)
        audience = feature["first_line"]["audience_tension_mechanisms"]
        self.assertIn("READER_TARGETING", audience)
        self.assertIn("PAIN_PROBLEM_ACTIVATION", audience)
        self.assertIn("CURIOSITY_GAP", feature["first_line"]["continuation_mechanisms"])
        self.assertIn("URGENCY", feature["first_line"]["continuation_mechanisms"])
        self.assertIn("CONTINUE_READING", feature["actions"]["hypotheses"])
        self.assertEqual("PSYCHOLOGY_HYPOTHESIS", feature["actions"]["evidence_mode"])
        self.assertNotIn("text", feature)
        self.assertIn("text_sha256", str(feature))

    def test_question_derives_reply_hypothesis_and_unknown_body_is_explicit(self) -> None:
        feature = build_v2_feature(
            "あなたはなぜ不安になる？",
            {"availability": "NO_PARENT", "cliffhanger_technique": "UNKNOWN"},
        )
        self.assertIn("QUESTION", feature["first_line"]["rhetorical_mechanisms"])
        self.assertIn("REPLY_OR_COMMENT", feature["actions"]["hypotheses"])
        self.assertIn("TENSION", feature["body"]["roles"])
        plain = build_v2_feature(
            "これは事実です", {"availability": "NO_PARENT", "cliffhanger_technique": "UNKNOWN"}
        )
        self.assertEqual(["UNKNOWN"], plain["body"]["roles"])


if __name__ == "__main__":
    unittest.main()
