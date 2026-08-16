"""Text-free, human-readable M4 Structural Pattern Report."""

import json
from pathlib import Path
from typing import Any, Dict, List

from social_content_engine.data.repository import Repository
from social_content_engine.generation.safe_pattern import GenerationSafePattern

REPORT_VERSION = "M4_STRUCTURAL_PATTERN_REPORT_V1"


def _formula(sequence: List[str]) -> str:
    return " -> ".join(sequence)


def build_structural_pattern_report(
    repository: Repository, structural_feature_run_id: int
) -> Dict[str, Any]:
    run = repository.connection.execute(
        "SELECT * FROM structural_feature_runs WHERE id = ?", (structural_feature_run_id,)
    ).fetchone()
    if run is None:
        raise KeyError("structural feature run not found")
    rows = repository.connection.execute(
        """SELECT id, pattern_kind, signature_json, member_count, distinct_source_count, confidence
           FROM structural_patterns
           WHERE structural_feature_run_id = ?
           ORDER BY pattern_kind, member_count DESC, signature_json""",
        (structural_feature_run_id,),
    ).fetchall()
    patterns: Dict[str, List[Dict[str, Any]]] = {
        "FIRST_LINE": [], "POST": [], "THREAD": [],
    }
    for row in rows:
        signature = json.loads(str(row["signature_json"]))
        sequence = signature.get("component_sequence")
        if not isinstance(sequence, list):
            sequence = ["OBSERVED_SELF_REPLY_TRANSITION"]
        metric_rows = repository.connection.execute(
            """SELECT m4_metric_snapshots.field_name, COUNT(*) AS observed_count
               FROM structural_pattern_members
               JOIN structural_feature_instances
                 ON structural_feature_instances.id =
                    structural_pattern_members.structural_feature_instance_id
               JOIN m4_metric_snapshots
                 ON m4_metric_snapshots.normalized_post_version_id =
                    structural_feature_instances.normalized_post_version_id
               WHERE structural_pattern_members.structural_pattern_id = ?
                 AND m4_metric_snapshots.dataset_snapshot_id = ?
               GROUP BY m4_metric_snapshots.field_name
               ORDER BY m4_metric_snapshots.field_name""",
            (int(row["id"]), int(run["dataset_snapshot_id"])),
        ).fetchall()
        performance_statistics = {
            str(metric["field_name"]) + "_observed": int(metric["observed_count"])
            for metric in metric_rows
        }
        item = GenerationSafePattern.from_aggregate({
            "pattern_kind": str(row["pattern_kind"]), "component_sequence": sequence,
            "abstract_formula": _formula(sequence), "support_count": int(row["member_count"]),
            "confidence": str(row["confidence"]), "taxonomy_version": str(run["taxonomy_version"]),
            "extractor_version": str(run["extractor_version"]),
            "performance_statistics": performance_statistics,
        }).as_dict()
        item["evidence_count"] = int(row["member_count"])
        item["distinct_source_count"] = int(row["distinct_source_count"])
        patterns[str(row["pattern_kind"])].append(item)
    instance_count = repository.connection.execute(
        "SELECT COUNT(*) AS count FROM structural_feature_instances "
        "WHERE structural_feature_run_id = ?",
        (structural_feature_run_id,),
    ).fetchone()
    unavailable_count = repository.connection.execute(
        """SELECT COUNT(*) AS count FROM structural_feature_instances
           WHERE structural_feature_run_id = ?
             AND json_extract(feature_json, '$.first_line_availability') = 'UNAVAILABLE'""",
        (structural_feature_run_id,),
    ).fetchone()
    snapshot = repository.connection.execute(
        """SELECT selection_spec_json FROM dataset_snapshots WHERE id = ?""",
        (int(run["dataset_snapshot_id"]),),
    ).fetchone()
    quality_rows = repository.connection.execute(
        """SELECT browser_text_quality_assessments.quality_status, COUNT(*) AS count
           FROM dataset_members
           JOIN browser_text_quality_assessments
             ON browser_text_quality_assessments.browser_observation_id =
                dataset_members.selected_browser_observation_id
           WHERE dataset_members.dataset_snapshot_id = ?
           GROUP BY browser_text_quality_assessments.quality_status
           ORDER BY browser_text_quality_assessments.quality_status""",
        (int(run["dataset_snapshot_id"]),),
    ).fetchall()
    return {
        "report_version": REPORT_VERSION,
        "structural_feature_run_id": structural_feature_run_id,
        "dataset_snapshot_id": int(run["dataset_snapshot_id"]),
        "source_text_stored": False,
        "coverage": {
            "instances": int(instance_count["count"]),
            "first_line_unavailable": int(unavailable_count["count"]),
        },
        "dataset_selection": json.loads(str(snapshot["selection_spec_json"]))
        if snapshot is not None else {},
        "selected_text_quality": {
            str(row["quality_status"]): int(row["count"]) for row in quality_rows
        },
        "top_first_line_component_patterns": patterns["FIRST_LINE"],
        "top_post_structure_patterns": patterns["POST"],
        "observed_thread_structure_patterns": patterns["THREAD"],
    }


def render_structural_pattern_report(report: Dict[str, Any]) -> str:
    lines = [
        "# STRUCTURAL PATTERN REPORT", "",
        "- Report version: " + str(report["report_version"]),
        "- Structural run: " + str(report["structural_feature_run_id"]),
        "- Source text stored in report: false", "",
        "## Coverage", "",
    ]
    for key, value in report["coverage"].items():
        lines.append("- {0}: {1}".format(key, value))
    lines.extend(["", "## Dataset quality", ""])
    selection = report.get("dataset_selection", {})
    if selection:
        lines.append("- Selection contract: " + str(selection.get("contract_version", "UNKNOWN")))
    for key, value in report.get("selected_text_quality", {}).items():
        lines.append("- {0}: {1}".format(key, value))
    sections = (
        ("Top First-Line Component Patterns", "top_first_line_component_patterns"),
        ("Top Post Structure Patterns", "top_post_structure_patterns"),
        ("Observed Thread Structure Patterns", "observed_thread_structure_patterns"),
    )
    for title, key in sections:
        lines.extend(["", "## " + title, ""])
        patterns = report[key]
        if not patterns:
            lines.append("INSUFFICIENT_EVIDENCE")
            continue
        for pattern in patterns:
            lines.extend([
                "- Formula: `" + str(pattern["abstract_formula"]) + "`",
                "  - Support / evidence: {0} / {1}".format(
                    pattern["support_count"], pattern["evidence_count"]
                ),
                "  - Distinct sources: " + str(pattern["distinct_source_count"]),
                "  - Confidence: " + str(pattern["confidence"]),
                "  - Observed metric coverage: "
                + json.dumps(pattern["performance_statistics"], sort_keys=True),
            ])
    lines.append("")
    return "\n".join(lines)


def write_structural_pattern_report(report: Dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_structural_pattern_report(report), encoding="utf-8")
