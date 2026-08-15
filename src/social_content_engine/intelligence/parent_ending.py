"""Deterministic, source-text-free parent ending feature extraction."""

import hashlib
import unicodedata
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

from social_content_engine.analyzer.preprocessing import build_analyzer_input, input_sha256
from social_content_engine.data.repository import Repository

EXTRACTOR_VERSION = "m2-parent-ending-v1"
FEATURE_CONTRACT_VERSION = "M2_PARENT_ENDING_V1"
MarkerScore = Union[int, str]

_EXPLICIT_CONTINUATION = ("続きは", "次回", "つづく", "続く", "to be continued")
_CLOSURE = ("以上", "まとめ", "終わり", "おわり", "でした。", "です。")


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _non_empty_lines(text: str) -> List[Tuple[int, int]]:
    lines: List[Tuple[int, int]] = []
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
            lines.append((offset + left, offset + right))
        offset += len(raw_line)
    return lines


def _terminal_mark(line: str) -> str:
    last = line[-1]
    if last in ("?", "？"):
        return "QUESTION"
    if last in ("!", "！"):
        return "EXCLAMATION"
    if last in (":", "："):
        return "COLON"
    if unicodedata.category(last).startswith(("P", "S")):
        return "OTHER"
    return "NONE"


def _ending_scores(line: str, terminal: str) -> Tuple[MarkerScore, MarkerScore, MarkerScore, str]:
    lower = line.lower()
    if any(marker in lower for marker in _EXPLICIT_CONTINUATION):
        return 3, 0, 3, "EXPLICIT_CONTINUATION"
    if line.endswith(("...", "…", "・・")):
        return 3, 0, 3, "ELLIPSIS"
    if terminal == "QUESTION":
        return 2, 0, 2, "UNANSWERED_QUESTION"
    if terminal == "COLON":
        return 2, 0, 2, "COLON_LEAD_IN"
    if any(line.endswith(marker) for marker in _CLOSURE):
        return 0, 3, 0, "NONE"
    if line.endswith(("。", ".")):
        return 0, 2, 0, "NONE"
    return 0, 1, 0, "NONE"


def _overlapping_labels(
    payload: Optional[Dict[str, Any]], field: str, start: int, end: int
) -> List[str]:
    if payload is None:
        return []
    labels: Set[str] = set()
    items = payload.get(field, [])
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


def _unavailable_feature(availability: str) -> Dict[str, Any]:
    unknown: MarkerScore = "UNKNOWN"
    return {
        "availability": availability,
        "windows": [],
        "terminal_mark": "NONE",
        "open_loop_score": unknown,
        "closure_score": unknown,
        "continuation_desire": unknown,
        "cliffhanger_technique": "UNKNOWN",
        "m1_action_labels": [],
        "m1_structure_labels": [],
    }


def build_parent_ending_feature(
    availability: str,
    text: Optional[str] = None,
    parent_analysis_payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build ending windows and closed marker features without retaining content."""
    if availability != "OBSERVED" or text is None:
        return _unavailable_feature(availability)
    lines = _non_empty_lines(text)
    if not lines:
        return _unavailable_feature("PARENT_TEXT_UNAVAILABLE")
    windows: List[Dict[str, Any]] = []
    for size in range(1, min(3, len(lines)) + 1):
        start = lines[-size][0]
        end = lines[-1][1]
        value = text[start:end]
        windows.append(
            {
                "non_empty_line_count": size,
                "start": start,
                "end": end,
                "text_sha256": hashlib.sha256(value.encode("utf-8")).hexdigest(),
                "char_count": len(value),
            }
        )
    last_start, last_end = lines[-1]
    last_line = text[last_start:last_end]
    terminal = _terminal_mark(last_line)
    open_loop, closure, continuation, technique = _ending_scores(last_line, terminal)
    return {
        "availability": "OBSERVED",
        "windows": windows,
        "terminal_mark": terminal,
        "open_loop_score": open_loop,
        "closure_score": closure,
        "continuation_desire": continuation,
        "cliffhanger_technique": technique,
        "m1_action_labels": _overlapping_labels(
            parent_analysis_payload, "actions", last_start, last_end
        ),
        "m1_structure_labels": _overlapping_labels(
            parent_analysis_payload, "structures", last_start, last_end
        ),
    }


def extract_parent_ending(
    repository: Repository,
    child_analysis_run_row_id: int,
    *,
    extracted_at: Callable[[], str] = _utc_now,
) -> Dict[str, Any]:
    """Resolve, extract, and persist a replay-safe parent ending feature."""
    source = repository.get_parent_ending_source(child_analysis_run_row_id)
    child = source["child"]
    child_payload = child["normalized_payload"]
    if not isinstance(child_payload, dict):
        raise RuntimeError("child normalized payload is not an object")
    child_input_sha256 = input_sha256(build_analyzer_input(child_payload))
    if child_input_sha256 != child["input_sha256"]:
        raise ValueError("child analysis input hash does not match normalized version")
    availability = str(source["availability"])
    parent_payload = source.get("parent_normalized_payload")
    parent_text: Optional[str] = None
    if isinstance(parent_payload, dict):
        parent_input = build_analyzer_input(parent_payload)
        parent_text = str(parent_input["text"])
    parent_analysis = source.get("parent_analysis_payload")
    feature = build_parent_ending_feature(
        availability,
        parent_text,
        parent_analysis if isinstance(parent_analysis, dict) else None,
    )
    parent_version_id = source.get("parent_normalized_post_version_id")
    parent_analysis_id = source.get("parent_analysis_run_row_id")
    persisted = repository.persist_parent_ending_feature(
        child_analysis_run_row_id=child_analysis_run_row_id,
        child_normalized_post_version_id=int(child["normalized_post_version_id"]),
        parent_normalized_post_version_id=(
            int(parent_version_id) if parent_version_id is not None else None
        ),
        parent_analysis_run_row_id=(
            int(parent_analysis_id) if parent_analysis_id is not None else None
        ),
        extractor_version=EXTRACTOR_VERSION,
        feature_contract_version=FEATURE_CONTRACT_VERSION,
        input_sha256=child_input_sha256,
        feature=feature,
        extracted_at=extracted_at(),
    )
    return {
        "child_analysis_run_row_id": child_analysis_run_row_id,
        "child_normalized_post_version_id": int(child["normalized_post_version_id"]),
        "parent_normalized_post_version_id": parent_version_id,
        "parent_analysis_run_row_id": parent_analysis_id,
        "extractor_version": EXTRACTOR_VERSION,
        "feature_contract_version": FEATURE_CONTRACT_VERSION,
        "input_sha256": child_input_sha256,
        **persisted,
    }
