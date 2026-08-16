"""Text-free decomposed M4 V2 Pattern aggregation."""

import json
from collections import defaultdict
from typing import Any, Dict, List

from social_content_engine.data.repository import Repository


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


def build_v2_pattern_report(repository: Repository, run_id: int) -> Dict[str, Any]:
    rows = repository.connection.execute(
        "SELECT feature_json FROM m4_intelligence_instances WHERE m4_intelligence_run_id = ?",
        (run_id,),
    ).fetchall()
    features = [json.loads(str(row["feature_json"])) for row in rows]
    first_lines = [{"labels": item["first_line"]["rhetorical_mechanisms"]} for item in features]
    bodies = [{"roles": item["body"]["roles"]} for item in features]
    endings = [{"labels": item["ending"]["internal_open_loop_mechanisms"]} for item in features]
    actions = [{"labels": item["actions"]["hypotheses"]} for item in features]
    return {
        "report_version": "M4_V2_VIRAL_PATTERN_REPORT_V1",
        "run_id": run_id,
        "top_first_line_patterns": _aggregate(first_lines, "labels"),
        "top_body_patterns": _aggregate(bodies, "roles"),
        "top_open_loop_patterns": _aggregate(endings, "labels"),
        "top_action_patterns": _aggregate(actions, "labels"),
        "coverage_diagnostic": {"instances": len(features), "source_text_stored": False},
    }
