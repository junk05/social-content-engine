"""Text-free decomposed M4 V2 Pattern aggregation."""

import json
from collections import defaultdict
from typing import Any, Dict, List

from social_content_engine.data.repository import Repository

METRIC_FIELDS = (
    "public_counters.view_count", "public_counters.like_count",
    "public_counters.reply_count", "public_counters.repost_count",
    "public_counters.quote_count", "public_counters.share_count",
)


def _key(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _aggregate(values: List[Dict[str, Any]], field: str) -> List[Dict[str, Any]]:
    groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for value in values:
        signature = value[field]
        if signature in (["UNKNOWN"], ["NONE"], {"roles": ["UNKNOWN"]}):
            continue
        groups[_key(signature)].append(signature)
    result = [
        {"mechanism": members[0], "support_count": len(members),
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
    first_lines = [{"labels": item["first_line"]["rhetorical_mechanisms"]} for item in features]
    bodies = [{"roles": item["body"]["roles"]} for item in features]
    endings = [{"labels": item["ending"]["internal_open_loop_mechanisms"]} for item in features]
    actions = [{"labels": item["actions"]["hypotheses"]} for item in features]
    metric_rows = repository.connection.execute(
        "SELECT field_name FROM m4_metric_snapshots WHERE dataset_snapshot_id = ?",
        (run["dataset_snapshot_id"],),
    ).fetchall()
    return {
        "report_version": "M4_V2_VIRAL_PATTERN_REPORT_V1",
        "run_id": run_id,
        "top_first_line_patterns": _aggregate(first_lines, "labels"),
        "top_body_patterns": _aggregate(bodies, "roles"),
        "top_open_loop_patterns": _aggregate(endings, "labels"),
        "top_action_patterns": _aggregate(actions, "labels"),
        "metric_coverage": metric_coverage(metric_rows),
        "coverage_diagnostic": {"instances": len(features), "source_text_stored": False},
    }
