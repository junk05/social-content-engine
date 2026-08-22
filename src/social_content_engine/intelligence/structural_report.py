"""Text-free, human-readable M4 Structural Pattern Report."""

import json
import statistics
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from social_content_engine.data.repository import Repository
from social_content_engine.generation.safe_pattern import GenerationSafePattern

REPORT_VERSION = "M4_STRUCTURAL_PATTERN_REPORT_V2"

_COMPONENT_LABELS = {
    "QUESTION": "問いかけ",
    "NEGATION": "否定・誤解の解除",
    "NUMBER": "数字による具体化",
    "LIST_PREVIEW": "リスト予告",
    "TARGET_READER": "対象読者の明示",
    "DIRECT_ADDRESS": "読者への直接呼びかけ",
    "EXPERIENCE_STATEMENT": "経験の提示",
    "TIME_OR_AGE_REFERENCE": "時間・年齢の具体化",
    "COMPARISON": "比較",
    "CONTRAST": "対比・転換",
    "CONDITION": "条件提示",
    "PROBLEM_STATEMENT": "悩み・問題の提示",
    "RESULT_STATEMENT": "結果・変化の提示",
    "REASON_PREVIEW": "理由の予告・説明",
    "CONCLUSION_PREVIEW": "結論の予告",
    "SECRET_REVEAL": "秘密・本音の開示",
    "INCOMPLETE_INFORMATION": "情報を残すオープンループ",
    "CONCRETE_SCENE": "具体的な場面",
    "EMOTIONAL_EXPRESSION": "感情の明示",
    "ADVICE_OR_COMMAND": "助言・行動指示",
    "QUOTE": "引用",
    "TRANSITION": "展開の接続",
    "CTA": "反応を促すCTA",
    "ROOT_HOOK": "親投稿のフック",
    "ROOT_OPEN_LOOP": "親投稿のオープンループ",
    "SELF_REPLY_DEVELOPMENT": "自己返信で展開",
    "SELF_REPLY_EXPLANATION": "自己返信で理由説明",
    "SELF_REPLY_CONTRAST": "自己返信で対比・転換",
    "SELF_REPLY_PAYOFF": "自己返信で結論・回収",
    "SELF_REPLY_CTA": "自己返信でCTA",
    "SELF_REPLY_OPEN_LOOP": "自己返信でも情報を残す",
}


def _formula(sequence: List[str]) -> str:
    return " -> ".join(sequence)


def build_structural_pattern_report(
    repository: Repository, structural_feature_run_id: int,
    *, comparison_run_id: Optional[int] = None,
    data_audit: Optional[Dict[str, Any]] = None,
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
    previous: Dict[Tuple[str, str], int] = {}
    if comparison_run_id is not None:
        previous = {
            (str(row["pattern_kind"]), str(row["signature_json"])): int(row["member_count"])
            for row in repository.connection.execute(
                """SELECT pattern_kind, signature_json, member_count
                FROM structural_patterns WHERE structural_feature_run_id = ?""",
                (comparison_run_id,),
            )
        }
    current_keys = set()
    for row in rows:
        signature = json.loads(str(row["signature_json"]))
        current_key = (str(row["pattern_kind"]), str(row["signature_json"]))
        current_keys.add(current_key)
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
        approximate_rows = repository.connection.execute(
            """WITH pattern_roots AS (
                 SELECT DISTINCT bridges.browser_post_identity_id
                 FROM structural_pattern_members members
                 JOIN structural_feature_instances instances
                   ON instances.id = members.structural_feature_instance_id
                 JOIN browser_normalized_bridges bridges
                   ON bridges.normalized_post_version_id =
                      instances.normalized_post_version_id
                 WHERE members.structural_pattern_id = ?
               ), latest_views AS (
                 SELECT observations.browser_post_identity_id,
                        MAX(approximate.id) AS approximate_id
                 FROM browser_approximate_view_observations approximate
                 JOIN browser_observations observations
                   ON observations.id = approximate.browser_observation_id
                 JOIN pattern_roots
                   ON pattern_roots.browser_post_identity_id =
                      observations.browser_post_identity_id
                 GROUP BY observations.browser_post_identity_id
               )
               SELECT approximate.view_band, COUNT(*) AS observed_count
               FROM latest_views
               JOIN browser_approximate_view_observations approximate
                 ON approximate.id = latest_views.approximate_id
               GROUP BY approximate.view_band
               ORDER BY approximate.view_band""",
            (int(row["id"]),),
        ).fetchall()
        approximate_values = [
            int(metric["normalized_approx"])
            for metric in repository.connection.execute(
                """WITH pattern_roots AS (
                     SELECT DISTINCT bridges.browser_post_identity_id
                     FROM structural_pattern_members members
                     JOIN structural_feature_instances instances
                       ON instances.id = members.structural_feature_instance_id
                     JOIN browser_normalized_bridges bridges
                       ON bridges.normalized_post_version_id =
                          instances.normalized_post_version_id
                     WHERE members.structural_pattern_id = ?
                   ), latest_views AS (
                     SELECT observations.browser_post_identity_id,
                            MAX(approximate.id) AS approximate_id
                     FROM browser_approximate_view_observations approximate
                     JOIN browser_observations observations
                       ON observations.id = approximate.browser_observation_id
                     JOIN pattern_roots
                       ON pattern_roots.browser_post_identity_id =
                          observations.browser_post_identity_id
                     GROUP BY observations.browser_post_identity_id
                   )
                   SELECT approximate.normalized_approx
                   FROM latest_views
                   JOIN browser_approximate_view_observations approximate
                     ON approximate.id = latest_views.approximate_id
                   ORDER BY approximate.normalized_approx""",
                (int(row["id"]),),
            )
        ]
        if approximate_rows:
            performance_statistics["approximate_views_observed"] = sum(
                int(metric["observed_count"]) for metric in approximate_rows
            )
            for metric in approximate_rows:
                performance_statistics[
                    "approximate_views_band_" + str(metric["view_band"])
                ] = int(metric["observed_count"])
            performance_statistics["approximate_views_median"] = int(
                statistics.median(approximate_values)
            )
            performance_statistics["approximate_views_high_band_count"] = sum(
                value >= 100000 for value in approximate_values
            )
        item = GenerationSafePattern.from_aggregate({
            "pattern_kind": str(row["pattern_kind"]), "component_sequence": sequence,
            "abstract_formula": _formula(sequence), "support_count": int(row["member_count"]),
            "confidence": str(row["confidence"]), "taxonomy_version": str(run["taxonomy_version"]),
            "extractor_version": str(run["extractor_version"]),
            "performance_statistics": performance_statistics,
        }).as_dict()
        item["evidence_count"] = int(row["member_count"])
        item["distinct_source_count"] = int(row["distinct_source_count"])
        previous_support = previous.get(current_key)
        item["comparison"] = {
            "status": "NEW" if previous_support is None else "REPEATED",
            "previous_support": previous_support,
            "support_delta": None if previous_support is None
            else int(row["member_count"]) - previous_support,
        }
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
    residual_count = int(repository.connection.execute(
        """SELECT COUNT(*) FROM structural_feature_instances
        WHERE structural_feature_run_id = ?
          AND NOT EXISTS (
            SELECT 1 FROM json_each(
              structural_feature_instances.feature_json,
              '$.first_line_component_sequence'
            ) WHERE value <> 'ASSERTION'
          )""",
        (structural_feature_run_id,),
    ).fetchone()[0])
    approximate_dataset_rows = repository.connection.execute(
        """WITH snapshot_roots AS (
             SELECT DISTINCT bridges.browser_post_identity_id
             FROM dataset_members
             JOIN browser_normalized_bridges bridges
               ON bridges.normalized_post_version_id =
                  dataset_members.normalized_post_version_id
             WHERE dataset_members.dataset_snapshot_id = ?
           ), latest_views AS (
             SELECT observations.browser_post_identity_id,
                    MAX(approximate.id) AS approximate_id
             FROM browser_approximate_view_observations approximate
             JOIN browser_observations observations
               ON observations.id = approximate.browser_observation_id
             JOIN snapshot_roots
               ON snapshot_roots.browser_post_identity_id =
                  observations.browser_post_identity_id
             GROUP BY observations.browser_post_identity_id
           )
           SELECT approximate.view_band, approximate.normalized_approx
           FROM latest_views
           JOIN browser_approximate_view_observations approximate
             ON approximate.id = latest_views.approximate_id""",
        (int(run["dataset_snapshot_id"]),),
    ).fetchall()
    view_bands: Dict[str, int] = {}
    for row in approximate_dataset_rows:
        key = str(row["view_band"])
        view_bands[key] = view_bands.get(key, 0) + 1
    thread_lengths: Dict[str, int] = {}
    for row in repository.connection.execute(
            """WITH eligible_roots AS (
              SELECT DISTINCT bridges.browser_post_identity_id
              FROM dataset_members
              JOIN browser_normalized_bridges bridges
                ON bridges.normalized_post_version_id =
                   dataset_members.normalized_post_version_id
              WHERE dataset_members.dataset_snapshot_id = ?
            ), latest AS (
              SELECT sequence.root_browser_post_identity_id,
                     MAX(sequence.detail_observation_id) AS detail_observation_id
              FROM browser_thread_sequence_observations sequence
              JOIN eligible_roots
                ON eligible_roots.browser_post_identity_id =
                   sequence.root_browser_post_identity_id
              WHERE sequence.relationship_evidence =
                    'DOM_CONTIGUOUS_ROOT_AUTHOR_CHAIN'
              GROUP BY sequence.root_browser_post_identity_id
            )
            SELECT COUNT(sequence.id) AS node_count
            FROM latest
            JOIN browser_thread_sequence_observations sequence
              ON sequence.detail_observation_id = latest.detail_observation_id
             AND sequence.relationship_evidence IN (
               'ROOT_DETAIL_PAGE', 'DOM_CONTIGUOUS_ROOT_AUTHOR_CHAIN'
             )
            GROUP BY latest.root_browser_post_identity_id""",
            (int(run["dataset_snapshot_id"]),),
        ):
        key = str(row["node_count"])
        thread_lengths[key] = thread_lengths.get(key, 0) + 1
    removed = [
        {"pattern_kind": kind, "component_sequence": json.loads(signature)["component_sequence"],
         "previous_support": support}
        for (kind, signature), support in sorted(previous.items())
        if (kind, signature) not in current_keys
    ]
    instance_total = int(instance_count["count"])
    rounded_count = len(approximate_dataset_rows)
    readiness = "NOT_READY"
    limitations = []
    if instance_total >= 100 and patterns["FIRST_LINE"] and patterns["POST"]:
        readiness = "READY_FOR_M5"
        if rounded_count < instance_total * 0.7 or len(patterns["THREAD"]) < 1:
            readiness = "READY_WITH_LIMITATIONS"
    if rounded_count < instance_total * 0.7:
        limitations.append("ROUNDED_VIEWS_COVERAGE_BELOW_70_PERCENT")
    if not patterns["THREAD"]:
        limitations.append("NO_GENERALIZED_THREAD_PATTERN")
    if residual_count:
        limitations.append("FIRST_LINE_TAXONOMY_RESIDUAL_PRESENT")
    return {
        "report_version": REPORT_VERSION,
        "structural_feature_run_id": structural_feature_run_id,
        "dataset_snapshot_id": int(run["dataset_snapshot_id"]),
        "source_text_stored": False,
        "coverage": {
            "instances": instance_total,
            "first_line_unavailable": int(unavailable_count["count"]),
            "first_line_no_specific_component": residual_count,
            "rounded_views_observed": rounded_count,
            "rounded_views_coverage_percent": round(
                100 * rounded_count / instance_total, 1
            ) if instance_total else 0.0,
        },
        "dataset_selection": json.loads(str(snapshot["selection_spec_json"]))
        if snapshot is not None else {},
        "selected_text_quality": {
            str(row["quality_status"]): int(row["count"]) for row in quality_rows
        },
        "approximate_views_semantics": {
            "use": "DESCRIPTIVE_BAND_DISTRIBUTION_ONLY",
            "precision": "ROUNDED",
            "exact_ranking": False,
            "causal_inference": False,
            "missing_is_zero": False,
            "raw_display_retained_in_source_store": True,
            "view_band_distribution": view_bands,
        },
        "data_audit": data_audit or {},
        "comparison_run_id": comparison_run_id,
        "removed_or_below_support_patterns": removed,
        "pattern_counts": {key: len(value) for key, value in patterns.items()},
        "thread_length_distribution": thread_lengths,
        "pattern_library_readiness": {
            "status": readiness,
            "limitations": limitations,
            "m5_start_authorized": False,
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
    audit = report.get("data_audit", {})
    if audit:
        lines.extend(["", "## Latest browser data audit", ""])
        for key, value in audit.items():
            rendered_value = json.dumps(value, ensure_ascii=False, sort_keys=True)
            lines.append("- {0}: {1}".format(key, rendered_value))
    lines.extend(["", "## Dataset quality", ""])
    selection = report.get("dataset_selection", {})
    if selection:
        lines.append("- Selection contract: " + str(selection.get("contract_version", "UNKNOWN")))
    for key, value in report.get("selected_text_quality", {}).items():
        lines.append("- {0}: {1}".format(key, value))
    semantics = report.get("approximate_views_semantics", {})
    if semantics:
        lines.extend([
            "", "## Approximate Views semantics", "",
            "- Use: " + str(semantics.get("use", "UNSPECIFIED")),
            "- Precision: " + str(semantics.get("precision", "UNSPECIFIED")),
            "- Exact ranking: false",
            "- Causal inference: false",
            "- Missing is zero: false",
            "- View bands: " + json.dumps(
                semantics.get("view_band_distribution", {}), sort_keys=True
            ),
        ])
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
            sequence = pattern.get("component_sequence")
            if not isinstance(sequence, list):
                sequence = str(pattern.get("abstract_formula", "")).split(" -> ")
            explanation = " -> ".join(
                _COMPONENT_LABELS.get(str(item), str(item))
                for item in sequence
            )
            lines.extend([
                "- Formula: `" + str(pattern["abstract_formula"]) + "`",
                "  - Human interpretation: " + explanation,
                "  - Support / evidence: {0} / {1}".format(
                    pattern["support_count"], pattern["evidence_count"]
                ),
                "  - Distinct sources: " + str(pattern["distinct_source_count"]),
                "  - Confidence: " + str(pattern["confidence"]),
                "  - Observed metric coverage: "
                + json.dumps(pattern["performance_statistics"], sort_keys=True),
                "  - Previous comparison: "
                + json.dumps(pattern.get("comparison", {}), sort_keys=True),
            ])
    lines.extend(["", "## Thread length distribution", ""])
    if report.get("thread_length_distribution"):
        for length, count in sorted(
            report["thread_length_distribution"].items(), key=lambda item: int(item[0])
        ):
            lines.append("- {0} nodes: {1} roots".format(length, count))
    else:
        lines.append("INSUFFICIENT_EVIDENCE")
    lines.extend(["", "## Patterns removed or below support", ""])
    removed = report.get("removed_or_below_support_patterns", [])
    if removed:
        for pattern in removed:
            lines.append("- {0}: `{1}` (previous support {2})".format(
                pattern["pattern_kind"], _formula(pattern["component_sequence"]),
                pattern["previous_support"],
            ))
    else:
        lines.append("None")
    readiness = report.get("pattern_library_readiness", {})
    lines.extend([
        "", "## Pattern Library readiness", "",
        "- Decision: " + str(readiness.get("status", "NOT_READY")),
        "- Limitations: " + json.dumps(readiness.get("limitations", [])),
        "- M5 start authorized: false",
        "", "## What cannot yet be concluded", "",
        "- Pattern frequency is not performance superiority.",
        "- Rounded Views are descriptive bands, not exact rankings.",
        "- Missing metrics are not zero.",
        "- No causal or viral prediction is made.",
    ])
    lines.append("")
    return "\n".join(lines)


def write_structural_pattern_report(report: Dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_structural_pattern_report(report), encoding="utf-8")
