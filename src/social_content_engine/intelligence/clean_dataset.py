"""Create a deterministic M4 browser snapshot that excludes invalid source text."""

import hashlib
import json
from typing import Any, Dict

from social_content_engine.data.browser_text_quality import (
    ASSESSOR_VERSION,
    classify_browser_text_quality,
)
from social_content_engine.data.repository import Repository

CLEAN_DATASET_VERSION = "m4-clean-browser-text-v1"
DETAIL_BATCH_DATASET_VERSION = "m4-detail-batch-analysis-v1"


def _canonical_json(value: Dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def assess_browser_source_text(repository: Repository) -> Dict[str, int]:
    """Assess unassessed browser source observations from their immutable payloads."""
    rows = repository.connection.execute(
        """SELECT browser_observations.id, browser_observations.canonical_payload_json
           FROM browser_observations
           LEFT JOIN browser_text_quality_assessments
             ON browser_text_quality_assessments.browser_observation_id = browser_observations.id
           WHERE browser_text_quality_assessments.id IS NULL
           ORDER BY browser_observations.id"""
    ).fetchall()
    counts: Dict[str, int] = {}
    for row in rows:
        payload = json.loads(str(row["canonical_payload_json"]))
        text = payload.get("text") if isinstance(payload, dict) else None
        status = classify_browser_text_quality(text)
        input_json = _canonical_json({"canonical_payload_json": str(row["canonical_payload_json"]),
                                     "assessor_version": ASSESSOR_VERSION})
        repository.assess_browser_text_quality(
            browser_observation_id=int(row["id"]), quality_status=status,
            input_sha256=hashlib.sha256(input_json.encode("utf-8")).hexdigest(),
        )
        counts[status] = counts.get(status, 0) + 1
    return counts


def prepare_detail_batch_analysis(
    repository: Repository, batch_id: int, dataset_key: str, version: int
) -> Dict[str, int]:
    """Bridge one completed detail batch into a clean, finalized delta snapshot."""
    batch = repository.connection.execute(
        """SELECT status FROM browser_detail_enrichment_batches WHERE id = ?""",
        (batch_id,),
    ).fetchone()
    if batch is None:
        raise KeyError("detail batch not found: " + str(batch_id))
    if batch["status"] != "COMPLETED":
        raise ValueError("detail batch analysis requires a COMPLETED batch")
    rows = repository.connection.execute(
        """SELECT browser_detail_enrichment_queue.id AS queue_id,
                  browser_post_identities.id AS browser_identity_id,
                  browser_post_identities.post_url,
                  browser_detail_attempts.detail_observation_id,
                  browser_normalized_versions.source_observation_id
           FROM browser_detail_enrichment_queue
           JOIN browser_post_identities
             ON browser_post_identities.id =
                browser_detail_enrichment_queue.browser_post_identity_id
           JOIN browser_detail_attempts
             ON browser_detail_attempts.id =
                browser_detail_enrichment_queue.last_attempt_id
            AND browser_detail_attempts.outcome = 'SUCCEEDED'
           JOIN browser_normalized_versions
             ON browser_normalized_versions.id =
                browser_post_identities.current_normalized_version_id
           WHERE browser_detail_enrichment_queue.active_batch_id = ?
             AND browser_detail_enrichment_queue.status = 'DETAIL_ENRICHED'
           ORDER BY browser_post_identities.id, browser_detail_enrichment_queue.id""",
        (batch_id,),
    ).fetchall()
    bridged = []
    new_assessments = 0
    for row in rows:
        bridge = repository.bridge_browser_post(str(row["post_url"]))
        is_latest_detail_source = (
            int(row["source_observation_id"]) == int(row["detail_observation_id"])
            and int(bridge["source_browser_observation_id"])
            == int(row["detail_observation_id"])
        )
        observation = repository.connection.execute(
            """SELECT canonical_payload_json FROM browser_observations
            WHERE id = ? AND observation_type = 'POST_DETAIL'""",
            (row["detail_observation_id"],),
        ).fetchone()
        if observation is None:
            raise ValueError("completed detail observation is unavailable")
        assessment = repository.connection.execute(
            """SELECT quality_status FROM browser_text_quality_assessments
            WHERE browser_observation_id = ?""",
            (row["detail_observation_id"],),
        ).fetchone()
        if assessment is None:
            payload = json.loads(str(observation["canonical_payload_json"]))
            text = payload.get("text") if isinstance(payload, dict) else None
            quality_status = classify_browser_text_quality(text)
            input_json = _canonical_json(
                {
                    "canonical_payload_json": str(
                        observation["canonical_payload_json"]
                    ),
                    "assessor_version": ASSESSOR_VERSION,
                }
            )
            repository.assess_browser_text_quality(
                browser_observation_id=int(row["detail_observation_id"]),
                quality_status=quality_status,
                input_sha256=hashlib.sha256(
                    input_json.encode("utf-8")
                ).hexdigest(),
            )
            new_assessments += 1
        else:
            quality_status = str(assessment["quality_status"])
        bridged.append((row, bridge, quality_status, is_latest_detail_source))

    selection_spec = {
        "contract_version": DETAIL_BATCH_DATASET_VERSION,
        "detail_batch_id": batch_id,
        "include_quality_status": "VALID_TEXT",
        "source": "threads_browser",
        "selection_order": "browser_identity_id_asc_then_queue_id_asc",
    }
    snapshot_id = repository.create_dataset_snapshot(
        dataset_key, version, selection_spec
    )
    selected = 0
    for _row, bridge, quality_status, is_latest_detail_source in bridged:
        if quality_status != "VALID_TEXT" or not is_latest_detail_source:
            continue
        repository.add_browser_dataset_member(
            snapshot_id,
            int(bridge["normalized_post_version_id"]),
            int(bridge["source_browser_observation_id"]),
            selected,
            {
                "contract_version": DETAIL_BATCH_DATASET_VERSION,
                "detail_batch_id": batch_id,
                "quality_status": "VALID_TEXT",
            },
        )
        selected += 1
    repository.finalize_dataset_snapshot(snapshot_id)
    return {
        "detail_batch_id": batch_id,
        "dataset_snapshot_id": snapshot_id,
        "enriched_count": len(rows),
        "valid_member_count": selected,
        "excluded_count": len(rows) - selected,
        "new_assessment_count": new_assessments,
    }


def create_clean_browser_dataset_snapshot(
    repository: Repository, *, dataset_key: str, version: int
) -> Dict[str, int]:
    """Freeze one version per identity whose bridged source has valid visible text."""
    assessment_counts = assess_browser_source_text(repository)
    selection_spec = {
        "contract_version": CLEAN_DATASET_VERSION,
        "include_quality_status": "VALID_TEXT",
        "exclude_quality_statuses": ["INVALID_TEXT_DATE_METADATA", "TEXT_UNAVAILABLE"],
        "source": "threads_browser",
        "selection_order": "browser_identity_id_asc_then_browser_version_desc",
    }
    snapshot_id = repository.create_dataset_snapshot(dataset_key, version, selection_spec)
    rows = repository.connection.execute(
        """SELECT browser_normalized_bridges.normalized_post_version_id,
                  browser_normalized_versions.source_observation_id,
                  browser_normalized_bridges.browser_post_identity_id,
                  browser_normalized_versions.version AS browser_version
           FROM browser_normalized_bridges
           JOIN browser_normalized_versions
             ON browser_normalized_versions.id =
                browser_normalized_bridges.browser_normalized_version_id
           JOIN browser_text_quality_assessments
             ON browser_text_quality_assessments.browser_observation_id =
                browser_normalized_versions.source_observation_id
           WHERE browser_text_quality_assessments.quality_status = 'VALID_TEXT'
           ORDER BY browser_normalized_bridges.browser_post_identity_id,
                    browser_normalized_versions.version DESC,
                    browser_normalized_bridges.id DESC"""
    ).fetchall()
    selected_identities = set()
    ordinal = 0
    for row in rows:
        identity_id = int(row["browser_post_identity_id"])
        if identity_id in selected_identities:
            continue
        repository.add_browser_dataset_member(
            snapshot_id, int(row["normalized_post_version_id"]),
            int(row["source_observation_id"]), ordinal,
            {"contract_version": CLEAN_DATASET_VERSION,
             "quality_status": "VALID_TEXT",
             "browser_identity_id": identity_id,
             "browser_normalized_version": int(row["browser_version"])},
        )
        selected_identities.add(identity_id)
        ordinal += 1
    repository.finalize_dataset_snapshot(snapshot_id)
    return {"dataset_snapshot_id": snapshot_id, "member_count": ordinal,
            "new_assessments": sum(assessment_counts.values())}
