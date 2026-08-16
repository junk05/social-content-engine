"""Deterministic, text-free M4 Hook/Body/Ending/Action feature derivation."""

from typing import Any, Dict, List

DERIVATION_VERSION = "m4-intelligence-v1"
FEATURE_CONTRACT_VERSION = "M4_INTELLIGENCE_FEATURE_V1"


def _labels(payload: Dict[str, Any], key: str) -> List[str]:
    value = payload.get(key)
    return sorted({str(item) for item in value}) if isinstance(value, list) else []


def build_intelligence_feature(
    first_line: Dict[str, Any], parent_ending: Dict[str, Any]
) -> Dict[str, Any]:
    """Derive only closed labels already supported by M1/M2 evidence."""
    family = str(first_line["hook_family"])
    subtype = str(first_line["hook_subtype"])
    structures = _labels(first_line, "m1_structure_labels")
    actions = _labels(first_line, "m1_action_labels")
    mechanisms = []
    if family == "QUESTION":
        mechanisms.append("QUESTION_GAP")
    if family == "CONTRARIAN":
        mechanisms.append("CONTRARIAN_CLAIM")
    if family == "TARGETED":
        mechanisms.append("DIRECT_RELEVANCE")
    if family == "EMOTIONAL":
        mechanisms.append("EMOTIONAL_TENSION")
    read_more = first_line.get("read_more_pressure", 0)
    if family == "OPEN_LOOP" or (isinstance(read_more, int) and read_more > 0):
        mechanisms.append("WITHHELD_REASON")
    if not mechanisms:
        mechanisms = ["NONE"]
    body_map = {
        "PROBLEM_SOLUTION": ["TENSION", "EXPLANATION", "PAYOFF"],
        "CONTRAST": ["REVERSAL"], "STORY_ARC": ["SETUP", "ESCALATION"],
        "QUESTION_LED": ["TENSION"], "CALL_TO_ACTION": ["TRANSITION"],
    }
    body_roles = sorted({role for label in structures for role in body_map.get(label, [])})
    expected = []
    if first_line.get("expected_action") == "CONTINUE_READING" or "OPEN_LOOP" in structures:
        expected.append("CONTINUE_READING")
    if "ASK" in actions or "INVITE_RESPONSE" in actions:
        expected.append("REPLY_OR_COMMENT")
    if "ADVISE" in actions:
        expected.append("SAVE_OR_SHARE")
    if not expected:
        expected = ["NONE"]
    return {
        "schema_version": 1,
        "hook": {
            "family": family, "subtype": subtype,
            "surprise_signal": "PRESENT" if family == "CONTRARIAN" else "ABSENT",
            "identity_targeting": "DIRECT" if family == "TARGETED" else "NONE",
            "information_state": (
                "INCOMPLETE" if family in {"QUESTION", "OPEN_LOOP"} else "COMPLETE"
            ),
            "implied_outcome": "UNKNOWN", "certainty_mode": "UNKNOWN",
            "continue_reading_mechanisms": sorted(mechanisms),
        },
        "body_roles": body_roles or ["UNKNOWN"],
        "ending": {
            "availability": parent_ending["availability"],
            "open_loop_score": parent_ending["open_loop_score"],
            "closure_score": parent_ending["closure_score"],
            "cliffhanger_technique": parent_ending["cliffhanger_technique"],
        },
        "expected_reader_actions": sorted(expected),
        "action_evidence_mode": "HYPOTHESIS",
        "m1_action_labels": actions,
        "m1_structure_labels": structures,
    }
