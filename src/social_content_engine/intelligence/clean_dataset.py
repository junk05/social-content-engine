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
