"""Text-free decomposed M4 V2 Pattern aggregation."""

import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List

from social_content_engine.data.repository import Repository

METRIC_FIELDS = (
    "public_counters.view_count", "public_counters.like_count",
    "public_counters.reply_count", "public_counters.repost_count",
    "public_counters.quote_count", "public_counters.share_count",
)
REPORT_VERSION = "M4_V2_VIRAL_PATTERN_REPORT_V3"


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


def _psychology_hypotheses(signature: Any) -> List[Dict[str, Any]]:
    """Return closed, non-causal reader-response hypotheses for a mechanism."""
    serialized = _key(signature)
    hypotheses: List[Dict[str, Any]] = []
    if "CONTRARIAN_CLAIM" in serialized or "EXPECTATION_REVERSAL" in serialized:
        hypotheses.append({
            "evidence_mode": "PSYCHOLOGY_HYPOTHESIS",
            "mechanism": "EXPECTATION_VIOLATION",
            "expected_reader_actions": ["ATTENTION", "CONTINUE_READING"],
        })
    if "READER_TARGETING" in serialized or "IDENTITY_CALLOUT" in serialized:
        hypotheses.append({
            "evidence_mode": "PSYCHOLOGY_HYPOTHESIS",
            "mechanism": "SELF_RELEVANCE",
            "expected_reader_actions": ["CONTINUE_READING"],
        })
    if "CURIOSITY_GAP" in serialized or "INCOMPLETE_INFORMATION" in serialized:
        hypotheses.append({
            "evidence_mode": "PSYCHOLOGY_HYPOTHESIS",
            "mechanism": "INFORMATION_GAP",
            "expected_reader_actions": ["CONTINUE_READING"],
        })
    if "QUESTION" in serialized:
        hypotheses.append({
            "evidence_mode": "PSYCHOLOGY_HYPOTHESIS",
            "mechanism": "RESPONSE_INVITATION",
            "expected_reader_actions": ["REPLY_OR_COMMENT"],
        })
    if "PAIN_PROBLEM_ACTIVATION" in serialized or "EMOTIONAL_VALIDATION" in serialized:
        hypotheses.append({
            "evidence_mode": "PSYCHOLOGY_HYPOTHESIS",
            "mechanism": "EMOTIONAL_RESONANCE",
            "expected_reader_actions": ["CONTINUE_READING"],
        })
    if "IMPLIED_BENEFIT" in serialized:
        hypotheses.append({
            "evidence_mode": "PSYCHOLOGY_HYPOTHESIS",
            "mechanism": "ANTICIPATED_UTILITY",
            "expected_reader_actions": ["SAVE"],
        })
    if "WARNING" in serialized or "IMPLIED_THREAT" in serialized:
        hypotheses.append({
            "evidence_mode": "PSYCHOLOGY_HYPOTHESIS",
            "mechanism": "LOSS_AVERSION",
            "expected_reader_actions": ["ATTENTION", "CONTINUE_READING"],
        })
    return hypotheses


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
         "psychology_hypotheses": _psychology_hypotheses(members[0]),
         "support_count": len(members), "evidence_count": len(members),
         "confidence": "MEDIUM" if len(members) >= 3 else "LOW"}
        for members in groups.values() if len(members) >= 2
    ]
    return sorted(result, key=lambda item: (-int(item["support_count"]), _key(item["mechanism"])))


def metric_coverage(rows: Iterable[Any]) -> Dict[str, Dict[str, Any]]:
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


def _first_line_signature(feature: Dict[str, Any]) -> Dict[str, Any]:
    first_line = feature["first_line"]
    return {
        "rhetorical": first_line["rhetorical_mechanisms"],
        "audience_tension": first_line["audience_tension_mechanisms"],
        "continuation": first_line["continuation_mechanisms"],
        "certainty": first_line["certainty_level"],
    }


def first_line_coverage(features: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Explain promotion loss without exposing any source text or identities."""
    available = [
        item for item in features
        if item["first_line"].get("availability", "OBSERVED") == "OBSERVED"
    ]
    signatures = [_first_line_signature(item) for item in available]
    signature_counts: Dict[str, int] = defaultdict(int)
    for signature in signatures:
        signature_counts[_key(signature)] += 1
    generic = [signature for signature in signatures if _is_generic_first_line(signature)]
    meaningful = [signature for signature in signatures if not _is_generic_first_line(signature)]
    supported = [
        signature for signature in meaningful if signature_counts[_key(signature)] >= 2
    ]
    promoted = {
        key for key, count in signature_counts.items()
        if count >= 2 and not _is_generic_first_line(json.loads(key))
    }
    frequency: Dict[str, Dict[str, int]] = {
        "rhetorical": defaultdict(int), "psychological": defaultdict(int),
        "certainty": defaultdict(int),
    }
    for signature in signatures:
        for label in signature["rhetorical"]:
            frequency["rhetorical"][label] += 1
        for label in signature["audience_tension"] + signature["continuation"]:
            if label != "NONE":
                frequency["psychological"][label] += 1
        if signature["certainty"] != "UNKNOWN":
            frequency["certainty"][signature["certainty"]] += 1
    return {
        "funnel": {
            "analyzed_posts": len(features),
            "first_line_available": len(available),
            "feature_detected": len(available),
            "no_meaningful_feature_detected": len(generic),
            "pattern_candidate": len(meaningful),
            "singleton_candidate": sum(
                1 for signature in meaningful if signature_counts[_key(signature)] == 1
            ),
            "support_gte_2": len(supported),
            "promoted_pattern": len(promoted),
            "excluded_generic_pattern": len(generic),
        },
        "feature_frequency": {
            dimension: dict(sorted(values.items(), key=lambda item: (-item[1], item[0])))
            for dimension, values in frequency.items()
        },
        "definitions": {
            "feature_detected": "A non-empty first line was deterministically classified.",
            "no_meaningful_feature_detected": (
                "Only generic ASSERTION/NONE/UNKNOWN labels were available."
            ),
            "pattern_candidate": "A non-generic first-line signature eligible for grouping.",
            "promoted_pattern": "A non-generic signature with support from two or more posts.",
        },
    }


def metric_collection_audit(
    repository: Repository, dataset_snapshot_id: int
) -> Dict[str, Dict[str, Any]]:
    """Audit browser-field capture independently from M4 snapshot selection."""
    rows = repository.connection.execute(
        """SELECT browser_observed_fields.field_name,
                  COUNT(*) AS observed_count,
                  COUNT(DISTINCT browser_observed_fields.browser_observation_id)
                    AS observation_count
           FROM dataset_members
           JOIN browser_normalized_bridges
             ON browser_normalized_bridges.normalized_post_version_id =
                dataset_members.normalized_post_version_id
           JOIN browser_observations
             ON browser_observations.browser_post_identity_id =
                browser_normalized_bridges.browser_post_identity_id
           JOIN browser_observed_fields
             ON browser_observed_fields.browser_observation_id = browser_observations.id
           WHERE dataset_members.dataset_snapshot_id = ?
             AND browser_observed_fields.field_name LIKE 'public_counters.%'
           GROUP BY browser_observed_fields.field_name
           ORDER BY browser_observed_fields.field_name""",
        (dataset_snapshot_id,),
    ).fetchall()
    observed = {str(row["field_name"]): {
        "observed_count": int(row["observed_count"]),
        "observation_count": int(row["observation_count"]),
        "status": "OBSERVED_BY_BROWSER_COLLECTOR",
    } for row in rows}
    return {field: observed.get(field, {
        "observed_count": 0, "observation_count": 0,
        "status": "NOT_OBSERVED_BY_BROWSER_COLLECTOR",
    }) for field in METRIC_FIELDS}


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
    first_lines = [{"signature": _first_line_signature(item)} for item in features]
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
        "metric_collection_audit": metric_collection_audit(
            repository, int(run["dataset_snapshot_id"])
        ),
        "first_line_coverage": first_line_coverage(features),
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
                "  - Psychology hypotheses: " + _key(item["psychology_hypotheses"]),
            ])
        lines.append("")
    lines.extend(["## First-Line coverage funnel", ""])
    for key, value in report["first_line_coverage"]["funnel"].items():
        lines.append("- {0}: {1}".format(key, value))
    lines.extend(["", "## First-Line feature frequency", ""])
    for dimension, values in report["first_line_coverage"]["feature_frequency"].items():
        lines.append("- {0}: {1}".format(dimension, _key(values)))
    lines.extend(["", "## M4 metric snapshot coverage", ""])
    for field, value in sorted(report["metric_coverage"].items()):
        lines.append("- {0}: {1} observed ({2})".format(
            field, value["observed_count"], value["status"]
        ))
    lines.extend(["", "## Browser metric collection audit", ""])
    for field, value in sorted(report["metric_collection_audit"].items()):
        lines.append("- {0}: {1} observed fields / {2} observations ({3})".format(
            field, value["observed_count"], value["observation_count"], value["status"]
        ))
    lines.append("")
    return "\n".join(lines)


def write_v2_pattern_report(report: Dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_v2_pattern_report(report), encoding="utf-8")
