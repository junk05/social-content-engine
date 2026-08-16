"""Text-free, deterministic M4 Viral Pattern Intelligence report."""

import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List

from social_content_engine.data.repository import Repository

from .m4_intelligence import sequence_signature


def build_viral_pattern_report(repository: Repository, m4_run_id: int) -> Dict[str, Any]:
    run = repository.connection.execute(
        "SELECT dataset_snapshot_id FROM m4_intelligence_runs WHERE id = ?", (m4_run_id,)
    ).fetchone()
    if run is None:
        raise KeyError("M4 intelligence run not found")
    groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    rows = repository.connection.execute(
        "SELECT feature_json, input_sha256 FROM m4_intelligence_instances "
        "WHERE m4_intelligence_run_id = ?",
        (m4_run_id,),
    ).fetchall()
    for row in rows:
        signature = sequence_signature(json.loads(str(row["feature_json"])))
        signature_key = json.dumps(
            signature, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        groups[signature_key].append(
            {"signature": signature, "input_sha256": str(row["input_sha256"])}
        )
    patterns = []
    for key, members in groups.items():
        patterns.append({
            "signature": members[0]["signature"], "support_count": len(members),
            "status": "REPEATED" if len(members) >= 2 else "EMERGING",
            "confidence": "MEDIUM" if len(members) >= 3 else "LOW",
            "member_input_sha256s": sorted(member["input_sha256"] for member in members),
        })
    patterns.sort(
        key=lambda item: (
            -int(item["support_count"]), json.dumps(item["signature"], sort_keys=True)
        )
    )
    metric_count = int(
        repository.connection.execute(
            "SELECT COUNT(*) FROM m4_metric_snapshots WHERE dataset_snapshot_id = ?",
            (run["dataset_snapshot_id"],),
        ).fetchone()[0]
    )
    open_loops = [
        item
        for item in patterns
        if item["signature"]["parent_ending_availability"] == "OBSERVED"
    ]
    sections = {
        "top_first_line_patterns": patterns,
        "top_open_loop_patterns": open_loops,
        "top_action_patterns": patterns,
        "hook_ending_combinations": patterns,
    }
    return {
        "report_version": "M4_VIRAL_PATTERN_REPORT_V1", "m4_run_id": m4_run_id,
        "dataset_snapshot_id": int(run["dataset_snapshot_id"]),
        **sections,
        "section_status": {
            name: "SUPPORTED" if items else "INSUFFICIENT_EVIDENCE"
            for name, items in sections.items()
        },
        "performance_association": {
            "status": "DESCRIPTIVE_ONLY" if metric_count >= 2 else "INSUFFICIENT_COVERAGE",
            "observed_metric_snapshot_count": metric_count,
            "note": "No causal or virality claim is made.",
        },
    }


def write_viral_pattern_report(
    report: Dict[str, Any], json_path: Path, markdown_path: Path
) -> None:
    """Write local review artifacts; callers use ignored data/reports paths."""
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    lines = ["# VIRAL_PATTERN_REPORT", "", "Descriptive evidence only; no causal claim.", ""]
    lines.append("Performance: " + str(report["performance_association"]["status"]))
    lines.append(
        "Observed metric snapshots: "
        + str(report["performance_association"]["observed_metric_snapshot_count"])
    )
    for section in (
        "top_first_line_patterns", "top_open_loop_patterns", "top_action_patterns",
        "hook_ending_combinations",
    ):
        lines.extend(["", "## " + section, "Status: " + report["section_status"][section]])
        for item in report[section]:
            lines.extend(["", "### " + item["status"], "- Support: " + str(item["support_count"])])
            lines.append(
                "- Signature: `"
                + json.dumps(item["signature"], ensure_ascii=False, sort_keys=True)
                + "`"
            )
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
