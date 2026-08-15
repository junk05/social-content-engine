"""Deterministic human-review reports for descriptive M2 patterns."""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from social_content_engine.data.repository import Repository

REPORT_VERSION = "M2_PATTERN_REVIEW_REPORT_V1"


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _payload(value: Any) -> Dict[str, Any]:
    parsed = json.loads(str(value))
    if not isinstance(parsed, dict):
        raise RuntimeError("report source payload is not an object")
    return parsed


def _evidence_display(
    payload: Dict[str, Any], feature: Dict[str, Any], *, max_chars: int
) -> Tuple[Optional[str], List[str]]:
    warnings: List[str] = []
    text = payload.get("text")
    if not isinstance(text, str):
        return None, ["SOURCE_TEXT_UNAVAILABLE"]
    start = feature.get("start")
    end = feature.get("end")
    expected = feature.get("text_sha256")
    if not isinstance(start, int) or not isinstance(end, int) or not isinstance(expected, str):
        return None, ["FEATURE_SPAN_UNAVAILABLE"]
    if start < 0 or end < start or end > len(text):
        return None, ["FEATURE_SPAN_INVALID"]
    value = text[start:end]
    if hashlib.sha256(value.encode("utf-8")).hexdigest() != expected:
        return None, ["FEATURE_HASH_MISMATCH"]
    display = value if len(value) <= max_chars else value[: max_chars - 1] + "…"
    return display, warnings


def _parent_display(
    repository: Repository, ending_row: Any, ending: Dict[str, Any], *, max_chars: int
) -> Tuple[Optional[str], List[str]]:
    availability = ending.get("availability")
    if availability != "OBSERVED":
        return None, ["PARENT_ENDING_" + str(availability)]
    parent_version_id = ending_row["parent_normalized_post_version_id"]
    if parent_version_id is None:
        return None, ["PARENT_VERSION_UNAVAILABLE"]
    parent = repository.connection.execute(
        "SELECT canonical_payload_json FROM normalized_post_versions WHERE id = ?",
        (int(parent_version_id),),
    ).fetchone()
    if parent is None:
        return None, ["PARENT_VERSION_UNAVAILABLE"]
    windows = ending.get("windows")
    if not isinstance(windows, list) or not windows or not isinstance(windows[0], dict):
        return None, ["PARENT_ENDING_SPAN_UNAVAILABLE"]
    payload = _payload(parent["canonical_payload_json"])
    return _evidence_display(payload, windows[0], max_chars=max_chars)


def _ranking_evidence(instances: List[Dict[str, Any]]) -> Dict[str, int]:
    authors = [
        instance["author_id"]
        for instance in instances
        if isinstance(instance["author_id"], str) and instance["author_id"]
    ]
    parent_support = sum(
        1
        for instance in instances
        if instance["parent_ending_availability"] == "OBSERVED"
        and instance["parent_evidence_display"] is not None
    )
    completeness = sum(int(instance["feature_completeness"]) for instance in instances)
    return {
        "member_support": len(instances),
        "distinct_observed_author_support": len(set(authors)),
        "author_coverage_count": len(authors),
        "author_coverage_total": len(instances),
        "parent_ending_evidence_support": parent_support,
        "feature_completeness": completeness,
        "feature_completeness_max": 4 * len(instances),
    }


def build_pattern_report(
    repository: Repository,
    *,
    dataset_snapshot_id: int,
    max_evidence_chars: int = 160,
    generated_at: Callable[[], str] = _utc_now,
) -> Dict[str, Any]:
    """Build a runtime-joined report; excerpts are never written back to pattern tables."""
    if max_evidence_chars < 16 or max_evidence_chars > 500:
        raise ValueError("max evidence chars must be between 16 and 500")
    pattern_rows = repository.connection.execute("SELECT * FROM patterns").fetchall()
    candidates: List[Dict[str, Any]] = []
    for pattern_row in pattern_rows:
        provenance = _payload(pattern_row["provenance_json"])
        if provenance.get("dataset_snapshot_id") != dataset_snapshot_id:
            continue
        signature = _payload(pattern_row["feature_signature_json"])
        ranking = _payload(pattern_row["ranking_json"])
        rows = repository.connection.execute(
            """SELECT pattern_instances.*, normalized_post_versions.canonical_payload_json,
                      first_line_features.feature_json AS first_feature_json,
                      parent_ending_features.feature_json AS ending_feature_json,
                      parent_ending_features.parent_normalized_post_version_id
            FROM pattern_instances
            JOIN normalized_post_versions
              ON normalized_post_versions.id = pattern_instances.normalized_post_version_id
            JOIN first_line_features
              ON first_line_features.id = pattern_instances.first_line_feature_id
            JOIN parent_ending_features
              ON parent_ending_features.id = pattern_instances.parent_ending_feature_id
            WHERE pattern_instances.pattern_id = ?
            ORDER BY pattern_instances.source, pattern_instances.source_post_id""",
            (int(pattern_row["id"]),),
        ).fetchall()
        instances: List[Dict[str, Any]] = []
        pattern_warnings: List[str] = []
        for row in rows:
            normalized = _payload(row["canonical_payload_json"])
            first = _payload(row["first_feature_json"])
            ending = _payload(row["ending_feature_json"])
            first_display, first_warnings = _evidence_display(
                normalized, first, max_chars=max_evidence_chars
            )
            parent_display, parent_warnings = _parent_display(
                repository, row, ending, max_chars=max_evidence_chars
            )
            warnings = first_warnings + parent_warnings
            author_id = normalized.get("author_id")
            if not isinstance(author_id, str) or not author_id:
                warnings.append("AUTHOR_ID_UNAVAILABLE")
                author_id = None
            completeness = sum(
                (
                    signature.get("first_line_hook_family") != "EMPTY",
                    signature.get("first_line_hook_subtype") != "EMPTY",
                    ending.get("availability") == "OBSERVED",
                    ending.get("cliffhanger_technique") != "UNKNOWN",
                )
            )
            pattern_warnings.extend(warnings)
            instances.append(
                {
                    "source": str(row["source"]),
                    "source_post_id": str(row["source_post_id"]),
                    "normalized_post_version_id": int(row["normalized_post_version_id"]),
                    "analysis_run_row_id": int(row["analysis_run_row_id"]),
                    "first_line_feature_id": int(row["first_line_feature_id"]),
                    "parent_ending_feature_id": int(row["parent_ending_feature_id"]),
                    "input_sha256": str(row["input_sha256"]),
                    "first_line_evidence_display": first_display,
                    "parent_ending_evidence_display": parent_display,
                    "parent_ending_availability": str(ending.get("availability")),
                    "warnings": sorted(set(warnings)),
                    "author_id": author_id,
                    "feature_completeness": completeness,
                }
            )
        evidence = _ranking_evidence(instances)
        public_instances = [
            {
                key: value
                for key, value in instance.items()
                if key not in {"author_id", "feature_completeness"}
            }
            for instance in instances
        ]
        candidates.append(
            {
                "pattern_id": int(pattern_row["id"]),
                "pattern_key": str(pattern_row["pattern_key"]),
                "version": int(pattern_row["version"]),
                "rank": int(ranking["rank"]),
                "ranking_method": str(ranking["method"]),
                "signature": signature,
                "member_count": int(pattern_row["member_count"]),
                "ranking_evidence": evidence,
                "instances": public_instances,
                "warnings": sorted(set(pattern_warnings)),
                "provenance": provenance,
                "review_status": str(pattern_row["review_status"]),
                "review_action": {"allowed": ["APPROVE", "REJECT"], "selected": None},
            }
        )
    candidates.sort(key=lambda item: (int(item["rank"]), str(item["pattern_key"])))
    return {
        "report_version": REPORT_VERSION,
        "dataset_snapshot_id": dataset_snapshot_id,
        "generated_at": generated_at(),
        "ranking_order": [
            "member_support_desc",
            "distinct_observed_author_support_desc",
            "parent_ending_evidence_support_desc",
            "feature_completeness_desc",
            "pattern_key_asc",
        ],
        "scope_note": "Descriptive evidence support only; no virality or effect prediction.",
        "candidate_count": len(candidates),
        "candidates": candidates,
    }


def render_pattern_report_markdown(report: Dict[str, Any]) -> str:
    """Render the JSON report as a compact human approval worksheet."""
    lines = [
        "# Pattern Human Review",
        "",
        "Descriptive evidence support only; no virality or effect prediction.",
        "",
        "Candidates: " + str(report["candidate_count"]),
    ]
    for candidate in report["candidates"]:
        lines.extend(
            [
                "",
                "## #{} {}".format(candidate["rank"], candidate["pattern_key"]),
                "",
                "- Review status: " + str(candidate["review_status"]),
                "- Members: " + str(candidate["member_count"]),
                "- Signature: `" + _canonical_markdown(candidate["signature"]) + "`",
                "- Ranking evidence: `"
                + _canonical_markdown(candidate["ranking_evidence"])
                + "`",
                "- Provenance: `" + _canonical_markdown(candidate["provenance"]) + "`",
                "- Decision: [ ] APPROVE  [ ] REJECT",
            ]
        )
        for instance in candidate["instances"]:
            first = _one_line(instance["first_line_evidence_display"])
            parent = _one_line(instance["parent_ending_evidence_display"])
            lines.append(
                "  - {}/{} | first: {} | parent: {} | warnings: {}".format(
                    instance["source"],
                    instance["source_post_id"],
                    first,
                    parent,
                    ", ".join(instance["warnings"]) or "none",
                )
            )
    return "\n".join(lines) + "\n"


def _canonical_markdown(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _one_line(value: Any) -> str:
    if value is None:
        return "UNAVAILABLE"
    return str(value).replace("\r", " ").replace("\n", " ").replace("|", "\\|")


def write_pattern_report(report: Dict[str, Any], json_path: Path, markdown_path: Path) -> None:
    """Write report artifacts; live callers should use ignored data/reports paths."""
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(render_pattern_report_markdown(report), encoding="utf-8")
