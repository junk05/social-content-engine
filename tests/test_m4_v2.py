import unittest

from social_content_engine.intelligence.m4_v2 import (
    DERIVATION_VERSION,
    SHORT_FORM_MAX_CHARS,
    build_v2_feature,
    classify_thread_form,
)


class M4V2Test(unittest.TestCase):
    def test_derivation_version_tracks_taxonomy_revision(self) -> None:
        self.assertEqual("m4-intelligence-v2.4", DERIVATION_VERSION)

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

    def test_short_forms_are_not_missing_and_self_reply_requires_observed_edge(self) -> None:
        standalone = classify_thread_form("短い完結投稿", [], observed_self_reply=False)
        self.assertEqual("STANDALONE_SHORT", standalone["form"])
        self.assertEqual("UNKNOWN", standalone["relationship_evidence_mode"])
        open_loop = build_v2_feature(
            "続きは…", {"availability": "NO_PARENT", "cliffhanger_technique": "UNKNOWN"}
        )
        self.assertEqual("OPEN_LOOP_SHORT", open_loop["thread_form"]["form"])
        self_reply = build_v2_feature(
            "完結している短文", {"availability": "NO_PARENT", "cliffhanger_technique": "UNKNOWN"},
            observed_self_reply=True,
        )
        self.assertEqual("PARENT_TO_SELF_REPLY", self_reply["thread_form"]["form"])
        self.assertTrue(self_reply["thread_form"]["observed_self_reply_transition"])
        long_form = classify_thread_form(
            "あ" * (SHORT_FORM_MAX_CHARS + 1), [], observed_self_reply=False
        )
        self.assertEqual("LONG_FORM", long_form["form"])

    def test_number_list_requires_a_list_structure_not_an_incidental_digit(self) -> None:
        incidental = build_v2_feature(
            "2026年の恋愛事情", {"availability": "NO_PARENT", "cliffhanger_technique": "UNKNOWN"}
        )
        self.assertNotIn("NUMBER_LIST", incidental["first_line"]["rhetorical_mechanisms"])
        listed = build_v2_feature(
            "恋愛で覚えておきたい3つの理由",
            {"availability": "NO_PARENT", "cliffhanger_technique": "UNKNOWN"},
        )
        self.assertIn("NUMBER_LIST", listed["first_line"]["rhetorical_mechanisms"])

    def test_empty_text_is_explicitly_unavailable_not_generic_assertion(self) -> None:
        feature = build_v2_feature(
            "", {"availability": "NO_PARENT", "cliffhanger_technique": "UNKNOWN"}
        )
        self.assertEqual("EMPTY", feature["first_line"]["availability"])
        self.assertEqual([], feature["first_line"]["rhetorical_mechanisms"])

    def test_exact_browser_date_metadata_does_not_displace_visible_post_first_line(self) -> None:
        feature = build_v2_feature(
            "2026/08/16\nあなたへ、実は大切なこと",
            {"availability": "NO_PARENT", "cliffhanger_technique": "UNKNOWN"},
        )
        self.assertIn("REVELATION", feature["first_line"]["rhetorical_mechanisms"])
        self.assertIn("READER_TARGETING", feature["first_line"]["audience_tension_mechanisms"])


if __name__ == "__main__":
    unittest.main()
