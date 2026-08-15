"""Deterministic, source-text-free First-Line feature extraction."""

import hashlib
import re
import unicodedata
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

from social_content_engine.analyzer.preprocessing import build_analyzer_input, input_sha256
from social_content_engine.data.repository import Repository

EXTRACTOR_VERSION = "m2-first-line-v1"
FEATURE_CONTRACT_VERSION = "M2_FIRST_LINE_V1"
MarkerScore = Union[int, str]

_QUESTION_MARKERS = ("?", "？")
_EXCLAMATION_MARKERS = ("!", "！")
_COLON_MARKERS = (":", "：")
_CURIOSITY_HIGH = ("実は", "なぜ", "理由", "続き", "知らない", "秘密")
_SELF_HIGH = ("あなた", "こんな人", "こんな方")
_SELF_LOW = ("私", "自分")
_TARGET_HIGH = re.compile(r"(?:人|方)(?:へ|に|向け)|初心者|経験者")
_EMOTION_HIGH = ("つらい", "怖い", "不安", "悔しい", "最高", "驚いた")
_CONTRARIAN_HIGH = ("常識は間違い", "逆です", "むしろ", "実は違う")
_CONTRARIAN_MEDIUM = ("でも", "しかし", "一方で", "実は")
_READ_MORE = ("続き", "理由", "なぜ", "結論", "ポイント", "→")


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _first_non_empty_line(text: str) -> Optional[Tuple[int, int, str]]:
    offset = 0
    for raw_line in text.splitlines(keepends=True):
        content = raw_line.rstrip("\r\n")
        left = 0
        while left < len(content) and content[left].isspace():
            left += 1
        right = len(content)
        while right > left and content[right - 1].isspace():
            right -= 1
        if left < right:
            return offset + left, offset + right, content[left:right]
        offset += len(raw_line)
    if text and not text.splitlines(keepends=True):
        stripped = text.strip()
        if stripped:
            start = text.index(stripped)
            return start, start + len(stripped), stripped
    return None


def _terminal_mark(line: str) -> str:
    last = line[-1]
    if last in _QUESTION_MARKERS:
        return "QUESTION"
    if last in _EXCLAMATION_MARKERS:
        return "EXCLAMATION"
    if last in _COLON_MARKERS:
        return "COLON"
    if unicodedata.category(last).startswith(("P", "S")):
        return "OTHER"
    return "NONE"


def _contains_any(line: str, markers: Tuple[str, ...]) -> bool:
    return any(marker in line for marker in markers)


def _marker_scores(line: str, terminal: str) -> Dict[str, MarkerScore]:
    curiosity = 3 if _contains_any(line, _CURIOSITY_HIGH) else (2 if terminal == "QUESTION" else 0)
    if _contains_any(line, _SELF_HIGH):
        self_relevance = 3
    elif _contains_any(line, _SELF_LOW):
        self_relevance = 1
    else:
        self_relevance = 0
    if _TARGET_HIGH.search(line):
        target_specificity = 3
    elif _contains_any(line, _SELF_HIGH):
        target_specificity = 2
    else:
        target_specificity = 0
    if _contains_any(line, _EMOTION_HIGH):
        emotional_intensity = 3
    elif terminal == "EXCLAMATION":
        emotional_intensity = 2
    elif any(0x1F000 <= ord(character) <= 0x1FAFF for character in line):
        emotional_intensity = 1
    else:
        emotional_intensity = 0
    if _contains_any(line, _CONTRARIAN_HIGH):
        contrarian_level = 3
    elif _contains_any(line, _CONTRARIAN_MEDIUM):
        contrarian_level = 2
    else:
        contrarian_level = 0
    if _contains_any(line, _READ_MORE):
        read_more_pressure = 2
    elif terminal == "COLON":
        read_more_pressure = 1
    else:
        read_more_pressure = 0
    return {
        "curiosity_gap": curiosity,
        "self_relevance": self_relevance,
        "target_specificity": target_specificity,
        "emotional_intensity": emotional_intensity,
        "contrarian_level": contrarian_level,
        "read_more_pressure": read_more_pressure,
    }


def _hook_classification(
    line: str, terminal: str, scores: Dict[str, MarkerScore]
) -> Tuple[str, str]:
    if int(scores["contrarian_level"]) >= 2:
        return "CONTRARIAN", "CONTRARIAN_ASSERTION"
    if terminal == "QUESTION":
        subtype = "WHY_QUESTION" if "なぜ" in line else "DIRECT_QUESTION"
        return "QUESTION", subtype
    if int(scores["target_specificity"]) >= 2:
        return "TARGETED", "AUDIENCE_CALL_OUT"
    if int(scores["emotional_intensity"]) >= 2:
        return "EMOTIONAL", "EMOTION_LED"
    if int(scores["read_more_pressure"]) >= 1:
        return "OPEN_LOOP", "CONTINUATION_CUE"
    return "STATEMENT", "PLAIN_STATEMENT"


def _expected_action(terminal: str, scores: Dict[str, MarkerScore]) -> str:
    if terminal == "QUESTION":
        return "ANSWER"
    if int(scores["read_more_pressure"]) >= 1:
        return "READ_MORE"
    if int(scores["self_relevance"]) >= 2 or int(scores["contrarian_level"]) >= 2:
        return "REFLECT"
    return "NONE"


def _overlapping_labels(
    analysis_payload: Dict[str, Any], field: str, start: int, end: int
) -> List[str]:
    labels: Set[str] = set()
    items = analysis_payload.get(field, [])
    if not isinstance(items, list):
        return []
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("label"), str):
            continue
        evidence = item.get("evidence", [])
        if not isinstance(evidence, list):
            continue
        if any(
            isinstance(span, dict)
            and isinstance(span.get("start"), int)
            and isinstance(span.get("end"), int)
            and span["start"] < end
            and span["end"] > start
            for span in evidence
        ):
            labels.add(str(item["label"]))
    return sorted(labels)


def build_first_line_feature(text: str, analysis_payload: Dict[str, Any]) -> Dict[str, Any]:
    """Build a closed-vocabulary feature without retaining line content."""
    line = _first_non_empty_line(text)
    if line is None:
        unknown: MarkerScore = "UNKNOWN"
        return {
            "availability": "EMPTY",
            "start": None,
            "end": None,
            "text_sha256": None,
            "char_count": 0,
            "terminal_mark": "NONE",
            "hook_family": "EMPTY",
            "hook_subtype": "EMPTY",
            "curiosity_gap": unknown,
            "self_relevance": unknown,
            "target_specificity": unknown,
            "emotional_intensity": unknown,
            "contrarian_level": unknown,
            "read_more_pressure": unknown,
            "expected_action": "NONE",
            "m1_action_labels": [],
            "m1_structure_labels": [],
        }
    start, end, line_value = line
    terminal = _terminal_mark(line_value)
    scores = _marker_scores(line_value, terminal)
    hook_family, hook_subtype = _hook_classification(line_value, terminal, scores)
    return {
        "availability": "OBSERVED",
        "start": start,
        "end": end,
        "text_sha256": hashlib.sha256(line_value.encode("utf-8")).hexdigest(),
        "char_count": len(line_value),
        "terminal_mark": terminal,
        "hook_family": hook_family,
        "hook_subtype": hook_subtype,
        **scores,
        "expected_action": _expected_action(terminal, scores),
        "m1_action_labels": _overlapping_labels(analysis_payload, "actions", start, end),
        "m1_structure_labels": _overlapping_labels(
            analysis_payload, "structures", start, end
        ),
    }


def extract_first_line(
    repository: Repository,
    analysis_run_row_id: int,
    *,
    extracted_at: Callable[[], str] = _utc_now,
) -> Dict[str, Any]:
    """Extract and persist one replay-safe First-Line feature from an M1 run."""
    source = repository.get_analysis_feature_source(analysis_run_row_id)
    normalized = source["normalized_payload"]
    if not isinstance(normalized, dict):
        raise RuntimeError("normalized analysis source is not an object")
    analyzer_input = build_analyzer_input(normalized)
    source_input_sha256 = input_sha256(analyzer_input)
    if source_input_sha256 != source["input_sha256"]:
        raise ValueError("analysis input hash does not match normalized version")
    payload = source["analysis_payload"]
    if not isinstance(payload, dict):
        raise RuntimeError("analysis payload is not an object")
    feature = build_first_line_feature(str(analyzer_input["text"]), payload)
    persisted = repository.persist_first_line_feature(
        analysis_run_row_id=analysis_run_row_id,
        normalized_post_version_id=int(source["normalized_post_version_id"]),
        extractor_version=EXTRACTOR_VERSION,
        feature_contract_version=FEATURE_CONTRACT_VERSION,
        input_sha256=source_input_sha256,
        feature=feature,
        extracted_at=extracted_at(),
    )
    return {
        "analysis_run_row_id": analysis_run_row_id,
        "normalized_post_version_id": int(source["normalized_post_version_id"]),
        "extractor_version": EXTRACTOR_VERSION,
        "feature_contract_version": FEATURE_CONTRACT_VERSION,
        "input_sha256": source_input_sha256,
        **persisted,
    }
