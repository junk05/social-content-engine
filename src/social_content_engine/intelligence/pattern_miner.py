"""Deterministic exact-match pattern mining over a finalized M2 dataset."""

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Mapping, Sequence

from social_content_engine.data.repository import (
    Repository,
    pattern_instance_input_sha256,
    pattern_set_input_sha256,
)

MINER_VERSION = "m2-pattern-miner-v1"
FEATURE_CONTRACT_VERSION = "M2_PATTERN_SIGNATURE_V1"
RANKING_METHOD = "member-count-cluster-key-v1"


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True
    )


def _cluster_key(signature: Dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(signature).encode("utf-8")).hexdigest()


def _sorted_labels(first: Dict[str, Any], ending: Dict[str, Any]) -> Dict[str, List[str]]:
    actions = {
        str(label)
        for field in (first.get("m1_action_labels", []), ending.get("m1_action_labels", []))
        if isinstance(field, list)
        for label in field
        if isinstance(label, str)
    }
    structures = {
        str(label)
        for field in (
            first.get("m1_structure_labels", []),
            ending.get("m1_structure_labels", []),
        )
        if isinstance(field, list)
        for label in field
        if isinstance(label, str)
    }
    return {"actions": sorted(actions), "structures": sorted(structures)}


def _select_instances(
    repository: Repository,
    *,
    dataset_snapshot_id: int,
    analyzer_version: str,
    taxonomy_version: str,
    prompt_version: str,
    model_provider: str,
    model_name: str,
    model_parameters: Dict[str, Any],
    first_line_extractor_version: str,
    parent_ending_extractor_version: str,
    created_at: str,
) -> List[Dict[str, Any]]:
    snapshot = repository.connection.execute(
        "SELECT status FROM dataset_snapshots WHERE id = ?", (dataset_snapshot_id,)
    ).fetchone()
    if snapshot is None or snapshot["status"] != "FINALIZED":
        raise ValueError("pattern mining requires a finalized dataset snapshot")
    rows = repository.connection.execute(
        """SELECT dataset_members.ordinal, normalized_posts.source,
                  normalized_posts.source_post_id, normalized_post_versions.id
                    AS normalized_post_version_id,
                  analysis_runs.id AS analysis_run_row_id,
                  analysis_runs.analysis_run_id, analysis_runs.input_sha256,
                  first_line_features.id AS first_line_feature_id,
                  first_line_features.input_sha256 AS first_line_input_sha256,
                  first_line_features.feature_sha256 AS first_line_feature_sha256,
                  first_line_features.feature_json AS first_line_feature_json,
                  parent_ending_features.id AS parent_ending_feature_id,
                  parent_ending_features.input_sha256 AS parent_ending_input_sha256,
                  parent_ending_features.feature_sha256 AS parent_ending_feature_sha256,
                  parent_ending_features.feature_json AS parent_ending_feature_json,
                  analysis_runs.analyzed_at
        FROM dataset_members
        JOIN dataset_snapshots ON dataset_snapshots.id = dataset_members.dataset_snapshot_id
        JOIN normalized_post_versions
          ON normalized_post_versions.id = dataset_members.normalized_post_version_id
        JOIN normalized_posts
          ON normalized_posts.id = normalized_post_versions.normalized_post_id
        JOIN analysis_runs
          ON analysis_runs.normalized_post_version_id = normalized_post_versions.id
        JOIN first_line_features
          ON first_line_features.analysis_run_row_id = analysis_runs.id
         AND first_line_features.extractor_version = ?
        JOIN parent_ending_features
          ON parent_ending_features.child_analysis_run_row_id = analysis_runs.id
         AND parent_ending_features.extractor_version = ?
        WHERE dataset_members.dataset_snapshot_id = ?
          AND dataset_snapshots.status = 'FINALIZED'
          AND analysis_runs.status = 'SUCCEEDED'
          AND analysis_runs.analyzer_version = ?
          AND analysis_runs.taxonomy_version = ?
          AND analysis_runs.prompt_version = ?
          AND analysis_runs.model_provider = ?
          AND analysis_runs.model_name = ?
          AND analysis_runs.model_parameters_json = ?
        ORDER BY dataset_members.ordinal, analysis_runs.analyzed_at DESC,
                 analysis_runs.analysis_run_id, analysis_runs.id""",
        (
            first_line_extractor_version,
            parent_ending_extractor_version,
            dataset_snapshot_id,
            analyzer_version,
            taxonomy_version,
            prompt_version,
            model_provider,
            model_name,
            _canonical_json(model_parameters),
        ),
    ).fetchall()
    selected: Dict[int, Dict[str, Any]] = {}
    for row in rows:
        version_id = int(row["normalized_post_version_id"])
        if version_id in selected:
            continue
        first = json.loads(str(row["first_line_feature_json"]))
        ending = json.loads(str(row["parent_ending_feature_json"]))
        if not isinstance(first, dict) or not isinstance(ending, dict):
            raise RuntimeError("pattern feature evidence is not an object")
        signature = {
            "first_line_hook_family": first.get("hook_family"),
            "first_line_hook_subtype": first.get("hook_subtype"),
            "parent_ending_availability": ending.get("availability"),
            "parent_cliffhanger_technique": ending.get("cliffhanger_technique"),
        }
        instance_hash = pattern_instance_input_sha256(
            analysis_input_sha256=str(row["input_sha256"]),
            first_line_input_sha256=str(row["first_line_input_sha256"]),
            first_line_feature_sha256=str(row["first_line_feature_sha256"]),
            parent_ending_input_sha256=str(row["parent_ending_input_sha256"]),
            parent_ending_feature_sha256=str(row["parent_ending_feature_sha256"]),
        )
        selected[version_id] = {
            "source": str(row["source"]),
            "source_post_id": str(row["source_post_id"]),
            "analysis_run_row_id": int(row["analysis_run_row_id"]),
            "normalized_post_version_id": version_id,
            "first_line_feature_id": int(row["first_line_feature_id"]),
            "parent_ending_feature_id": int(row["parent_ending_feature_id"]),
            "extractor_version": MINER_VERSION,
            "feature_contract_version": FEATURE_CONTRACT_VERSION,
            "input_sha256": instance_hash,
            "feature": signature,
            "labels": _sorted_labels(first, ending),
            "created_at": created_at,
        }
    return list(selected.values())


def mine_patterns(
    repository: Repository,
    *,
    dataset_snapshot_id: int,
    analyzer_version: str,
    taxonomy_version: str,
    prompt_version: str,
    model_provider: str,
    model_name: str,
    model_parameters: Dict[str, Any],
    first_line_extractor_version: str,
    parent_ending_extractor_version: str,
    pattern_version: int = 1,
    now: Callable[[], str] = _utc_now,
) -> Dict[str, Any]:
    """Mine exact signatures; conflict choice is latest analyzed_at then run ID then row ID."""
    created_at = now()
    selected = _select_instances(
        repository,
        dataset_snapshot_id=dataset_snapshot_id,
        analyzer_version=analyzer_version,
        taxonomy_version=taxonomy_version,
        prompt_version=prompt_version,
        model_provider=model_provider,
        model_name=model_name,
        model_parameters=model_parameters,
        first_line_extractor_version=first_line_extractor_version,
        parent_ending_extractor_version=parent_ending_extractor_version,
        created_at=created_at,
    )
    clusters: Dict[str, List[Dict[str, Any]]] = {}
    for instance in selected:
        signature = instance["feature"]
        if not isinstance(signature, dict):
            raise RuntimeError("pattern signature is not an object")
        clusters.setdefault(_cluster_key(signature), []).append(instance)
    ordered = sorted(clusters.items(), key=lambda item: (-len(item[1]), item[0]))
    promoted: List[Dict[str, Any]] = []
    singletons: List[Dict[str, Any]] = []
    promoted_rank = 0
    for cluster_key, members in ordered:
        members.sort(key=lambda item: (str(item["source"]), str(item["source_post_id"])))
        signature = members[0]["feature"]
        if not isinstance(signature, dict):
            raise RuntimeError("pattern signature is not an object")
        labels = {
            "actions": sorted(
                {
                    label
                    for member in members
                    for label in member["labels"]["actions"]
                }
            ),
            "structures": sorted(
                {
                    label
                    for member in members
                    for label in member["labels"]["structures"]
                }
            ),
        }
        summary = {
            "cluster_key": cluster_key,
            "member_count": len(members),
            "exact_match": True,
            "distance": 0,
            "feature_signature": signature,
            "labels": labels,
            "member_input_sha256s": sorted(str(member["input_sha256"]) for member in members),
        }
        if len(members) < 2:
            singletons.append(summary)
            continue
        promoted_rank += 1
        set_hash = pattern_set_input_sha256(
            [str(member["input_sha256"]) for member in members], signature
        )
        instances: Sequence[Dict[str, Any]] = [
            {key: value for key, value in member.items() if key != "labels"}
            for member in members
        ]
        pattern_id = repository.create_pattern(
            pattern_key="m2-pattern-v1:" + cluster_key,
            version=pattern_version,
            feature_signature=signature,
            ranking={
                "method": RANKING_METHOD,
                "score": len(members),
                "rank": promoted_rank,
            },
            provenance={
                "dataset_snapshot_id": dataset_snapshot_id,
                "miner_version": MINER_VERSION,
                "feature_contract_version": FEATURE_CONTRACT_VERSION,
                "input_sha256": set_hash,
            },
            review_status="PENDING",
            instances=instances,
            created_at=created_at,
            replace_derived=True,
        )
        promoted.append({**summary, "pattern_id": pattern_id, "rank": promoted_rank})
    return {
        "dataset_snapshot_id": dataset_snapshot_id,
        "miner_version": MINER_VERSION,
        "feature_contract_version": FEATURE_CONTRACT_VERSION,
        "selected_instance_count": len(selected),
        "patterns": promoted,
        "singletons": singletons,
    }
