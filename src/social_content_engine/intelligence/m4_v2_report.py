"""Text-free decomposed M4 V2 Pattern aggregation."""

import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List

from social_content_engine.data.repository import Repository

METRIC_FIELDS = (
    "public_counters.view_count", "public_counters.like_count",
    "public_counters.reply_count", "public_counters.repost_count",
    "public_counters.quote_count", "public_counters.share_count",
)
REPORT_VERSION = "M4_V2_VIRAL_PATTERN_REPORT_V2"


def _key(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _is_generic_first_line(signature: Any) -> bool:
    return (
        isinstance(signature, dict)
        and signature == {
            "audience_tension": [], "certainty": "UNKNOWN",
            "continuation": ["NONE"], "rhetorical": ["ASSERTION"],
        }
    )


def _abstract_formula(signature: Any) -> str:
    if isinstance(signature, dict):
        parts = []
        for key in ("rhetorical", "audience_tension", "continuation", "certainty"):
            value = signature.get(key)
            if value in (None, [], ["NONE"], "UNKNOWN"):
                continue
            parts.append(key.upper() + ":" + _key(value))
        return " -> ".join(parts) or "UNSPECIFIED"
    return _key(signature)


def _psychological_effect(signature: Any) -> str:
    serialized = _key(signature)
    if "CURIOSITY_GAP" in serialized or "INCOMPLETE_INFORMATION" in serialized:
        return "CONTINUE_READING_HYPOTHESIS"
    if "QUESTION" in serialized:
        return "REPLY_OR_COMMENT_HYPOTHESIS"
    if "PAIN_PROBLEM_ACTIVATION" in serialized or "EMOTIONAL_VALIDATION" in serialized:
        return "SELF_RELEVANCE_HYPOTHESIS"
    if "IMPLIED_BENEFIT" in serialized:
        return "SAVE_HYPOTHESIS"
    return "UNSPECIFIED"


def _aggregate(values: List[Dict[str, Any]], field: str) -> List[Dict[str, Any]]:
    groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for value in values:
        signature = value[field]
        if (
            signature in (["UNKNOWN"], ["NONE"], {"roles": ["UNKNOWN"]})
            or _is_generic_first_line(signature)
        ):
            continue
        groups[_key(signature)].append(signature)
    result = [
        {"mechanism": members[0], "abstract_formula": _abstract_formula(members[0]),
         "expected_psychological_effect": _psychological_effect(members[0]),
         "support_count": len(members), "evidence_count": len(members),
         "confidence": "MEDIUM" if len(members) >= 3 else "LOW"}
        for members in groups.values() if len(members) >= 2
    ]
    return sorted(result, key=lambda item: (-int(item["support_count"]), _key(item["mechanism"])))


def metric_coverage(rows: List[Any]) -> Dict[str, Dict[str, Any]]:
    """Report coverage per observed metric; never infer a missing counter."""
    counts = {field: 0 for field in METRIC_FIELDS}
    for row in rows:
        field = str(row["field_name"])
        if field in counts:
            counts[field] += 1
    return {
        field: {
            "observed_count": count,
            "status": "DESCRIPTIVE_ONLY" if count >= 2 else "INSUFFICIENT_COVERAGE",
        }
        for field, count in counts.items()
    }


def build_v2_pattern_report(repository: Repository, run_id: int) -> Dict[str, Any]:
    run = repository.connection.execute(
        "SELECT dataset_snapshot_id FROM m4_intelligence_runs WHERE id = ?", (run_id,)
    ).fetchone()
    if run is None:
        raise KeyError("M4 intelligence run not found")
    rows = repository.connection.execute(
        "SELECT feature_json FROM m4_intelligence_instances WHERE m4_intelligence_run_id = ?",
        (run_id,),
    ).fetchall()
    features = [json.loads(str(row["feature_json"])) for row in rows]
    first_lines = [{"signature": {
        "rhetorical": item["first_line"]["rhetorical_mechanisms"],
        "audience_tension": item["first_line"]["audience_tension_mechanisms"],
        "continuation": item["first_line"]["continuation_mechanisms"],
        "certainty": item["first_line"]["certainty_level"],
    }} for item in features]
    bodies = [{"roles": item["body"]["roles"]} for item in features]
    endings = [{"labels": item["ending"]["internal_open_loop_mechanisms"]} for item in features]
    actions = [{"labels": item["actions"]["hypotheses"]} for item in features]
    thread_forms = [{"labels": [item["thread_form"]["form"]]} for item in features]
    metric_rows = repository.connection.execute(
        "SELECT field_name FROM m4_metric_snapshots WHERE dataset_snapshot_id = ?",
        (run["dataset_snapshot_id"],),
    ).fetchall()
    return {
        "report_version": REPORT_VERSION,
        "run_id": run_id,
        "top_first_line_patterns": _aggregate(first_lines, "signature"),
        "top_body_patterns": _aggregate(bodies, "roles"),
        "top_open_loop_patterns": _aggregate(endings, "labels"),
        "top_action_patterns": _aggregate(actions, "labels"),
        "top_thread_form_patterns": _aggregate(thread_forms, "labels"),
        "metric_coverage": metric_coverage(metric_rows),
        "coverage_diagnostic": {"instances": len(features), "source_text_stored": False},
    }


def render_v2_pattern_report(report: Dict[str, Any]) -> str:
    """Render closed Pattern intelligence without source-post content or identifiers."""
    lines = [
        "# VIRAL PATTERN REPORT",
        "",
        "- Report version: " + str(report["report_version"]),
        "- M4 run: " + str(report["run_id"]),
        "- Source text stored in report: false",
        "",
    ]
    sections = (
        ("Top First-Line Patterns", "top_first_line_patterns"),
        ("Top Body Patterns", "top_body_patterns"),
        ("Top Open-Loop Patterns", "top_open_loop_patterns"),
        ("Top Action Patterns", "top_action_patterns"),
        ("Thread Form Patterns", "top_thread_form_patterns"),
    )
    for title, key in sections:
        lines.extend(["## " + title, ""])
        items = report[key]
        if not items:
            lines.extend(["No actionable pattern with two or more evidence items.", ""])
            continue
        for item in items:
            lines.extend([
                "- Formula: `" + str(item["abstract_formula"]) + "`",
                "  - Support / evidence: {0} / {1}".format(
                    item["support_count"], item["evidence_count"]
                ),
                "  - Confidence: " + str(item["confidence"]),
                "  - Expected psychological effect: "
                + str(item["expected_psychological_effect"]),
            ])
        lines.append("")
    lines.extend(["## Metric coverage", ""])
    for field, value in sorted(report["metric_coverage"].items()):
        lines.append("- {0}: {1} observed ({2})".format(
            field, value["observed_count"], value["status"]
        ))
    lines.append("")
    return "\n".join(lines)


def write_v2_pattern_report(report: Dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_v2_pattern_report(report), encoding="utf-8")
