"""Deterministic, text-free M4 Hook/Body/Ending/Action feature derivation."""

import hashlib
import json
from typing import Any, Dict, List

from social_content_engine.data.repository import Repository

DERIVATION_VERSION = "m4-intelligence-v1"
FEATURE_CONTRACT_VERSION = "M4_INTELLIGENCE_FEATURE_V1"


def _labels(payload: Dict[str, Any], key: str) -> List[str]:
    value = payload.get(key)
    return sorted({str(item) for item in value}) if isinstance(value, list) else []


def build_intelligence_feature(
    first_line: Dict[str, Any], parent_ending: Dict[str, Any]
) -> Dict[str, Any]:
    """Derive only closed labels already supported by M1/M2 evidence."""
    family = str(first_line["hook_family"])
    subtype = str(first_line["hook_subtype"])
    structures = _labels(first_line, "m1_structure_labels")
    actions = _labels(first_line, "m1_action_labels")
    mechanisms = []
    if family == "QUESTION":
        mechanisms.append("QUESTION_GAP")
    if family == "CONTRARIAN":
        mechanisms.append("CONTRARIAN_CLAIM")
    if family == "TARGETED":
        mechanisms.append("DIRECT_RELEVANCE")
    if family == "EMOTIONAL":
        mechanisms.append("EMOTIONAL_TENSION")
    read_more = first_line.get("read_more_pressure", 0)
    if family == "OPEN_LOOP" or (isinstance(read_more, int) and read_more > 0):
        mechanisms.append("WITHHELD_REASON")
    if not mechanisms:
        mechanisms = ["NONE"]
    body_map = {
        "PROBLEM_SOLUTION": ["TENSION", "EXPLANATION", "PAYOFF"],
        "CONTRAST": ["REVERSAL"], "STORY_ARC": ["SETUP", "ESCALATION"],
        "QUESTION_LED": ["TENSION"], "CALL_TO_ACTION": ["TRANSITION"],
    }
    body_roles = sorted({role for label in structures for role in body_map.get(label, [])})
    expected = []
    if first_line.get("expected_action") == "CONTINUE_READING" or "OPEN_LOOP" in structures:
        expected.append("CONTINUE_READING")
    if "ASK" in actions or "INVITE_RESPONSE" in actions:
        expected.append("REPLY_OR_COMMENT")
    if "ADVISE" in actions:
        expected.append("SAVE_OR_SHARE")
    if not expected:
        expected = ["NONE"]
    return {
        "schema_version": 1,
        "hook": {
            "family": family, "subtype": subtype,
            "surprise_signal": "PRESENT" if family == "CONTRARIAN" else "ABSENT",
            "identity_targeting": "DIRECT" if family == "TARGETED" else "NONE",
            "information_state": (
                "INCOMPLETE" if family in {"QUESTION", "OPEN_LOOP"} else "COMPLETE"
            ),
            "implied_outcome": "UNKNOWN", "certainty_mode": "UNKNOWN",
            "continue_reading_mechanisms": sorted(mechanisms),
        },
        "body_roles": body_roles or ["UNKNOWN"],
        "ending": {
            "availability": parent_ending["availability"],
            "open_loop_score": parent_ending["open_loop_score"],
            "closure_score": parent_ending["closure_score"],
            "cliffhanger_technique": parent_ending["cliffhanger_technique"],
        },
        "expected_reader_actions": sorted(expected),
        "action_evidence_mode": "HYPOTHESIS",
        "m1_action_labels": actions,
        "m1_structure_labels": structures,
    }


def _canonical_json(value: Dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def sequence_signature(feature: Dict[str, Any]) -> Dict[str, Any]:
    """Return the text-free canonical Hook -> Body -> Ending -> Action signature."""
    hook = feature["hook"]
    ending = feature["ending"]
    return {
        "hook_family": hook["family"],
        "hook_subtype": hook["subtype"],
        "continue_reading_mechanisms": sorted(hook["continue_reading_mechanisms"]),
        "body_roles": sorted(feature["body_roles"]),
        "parent_ending_availability": ending["availability"],
        "parent_cliffhanger_technique": ending["cliffhanger_technique"],
        "expected_reader_actions": sorted(feature["expected_reader_actions"]),
    }


def materialize_metric_snapshots(repository: Repository, dataset_snapshot_id: int) -> int:
    """Copy only explicitly observed browser counters into append-only M4 rows."""
    rows = repository.connection.execute(
        """SELECT dataset_members.normalized_post_version_id, browser_observed_fields.*
           FROM dataset_members
           JOIN browser_normalized_bridges
             ON browser_normalized_bridges.normalized_post_version_id =
                dataset_members.normalized_post_version_id
           JOIN browser_normalized_versions
             ON browser_normalized_versions.id =
                browser_normalized_bridges.browser_normalized_version_id
           JOIN browser_observed_fields
             ON browser_observed_fields.browser_observation_id =
                browser_normalized_versions.source_observation_id
           WHERE dataset_members.dataset_snapshot_id = ?
             AND browser_observed_fields.field_name LIKE 'public_counters.%'
           ORDER BY dataset_members.ordinal, browser_observed_fields.id""",
        (dataset_snapshot_id,),
    ).fetchall()
    inserted = 0
    for row in rows:
        value = json.loads(str(row["observed_value_json"]))
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            continue
        document = {
            "browser_observation_id": row["browser_observation_id"],
            "field_name": row["field_name"], "value": value,
            "observed_at": row["observed_at"], "extractor_version": row["extractor_version"],
            "metric_version": "m4-performance-v1",
        }
        input_sha256 = hashlib.sha256(_canonical_json(document).encode("utf-8")).hexdigest()
        cursor = repository.connection.execute(
            """INSERT OR IGNORE INTO m4_metric_snapshots
            (dataset_snapshot_id, normalized_post_version_id, browser_observation_id,
             field_name, metric_value, observed_at, surface, extractor_version,
             input_sha256, metric_version) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (dataset_snapshot_id, row["normalized_post_version_id"], row["browser_observation_id"],
             row["field_name"], value, row["observed_at"], row["surface"],
             row["extractor_version"], input_sha256,
             "m4-performance-v1"),
        )
        inserted += cursor.rowcount
    repository.connection.commit()
    return inserted


def materialize_sequence_patterns(repository: Repository, m4_intelligence_run_id: int) -> int:
    """Persist only repeated, text-free sequence patterns for one pinned M4 run."""
    rows = repository.connection.execute(
        """SELECT m4_intelligence_instances.id, m4_intelligence_instances.feature_json,
                  m4_intelligence_instances.input_sha256,
                  normalized_post_versions.normalized_post_id
           FROM m4_intelligence_instances
           JOIN normalized_post_versions
             ON normalized_post_versions.id = m4_intelligence_instances.normalized_post_version_id
           WHERE m4_intelligence_instances.m4_intelligence_run_id = ?
           ORDER BY m4_intelligence_instances.id""",
        (m4_intelligence_run_id,),
    ).fetchall()
    groups: Dict[str, List[Any]] = {}
    for row in rows:
        signature = sequence_signature(json.loads(str(row["feature_json"])))
        signature_json = _canonical_json(signature)
        groups.setdefault(signature_json, []).append(row)
    inserted = 0
    for signature_json in sorted(groups):
        members = groups[signature_json]
        sources = {int(member["normalized_post_id"]) for member in members}
        if len(members) < 2 or len(sources) < 2:
            continue
        signature_sha256 = hashlib.sha256(signature_json.encode("utf-8")).hexdigest()
        input_document = {
            "signature_sha256": signature_sha256,
            "member_input_sha256s": sorted(str(member["input_sha256"]) for member in members),
            "sequence_miner_version": "m4-sequence-miner-v1",
        }
        input_sha256 = hashlib.sha256(_canonical_json(input_document).encode("utf-8")).hexdigest()
        existing = repository.connection.execute(
            """SELECT id, input_sha256 FROM m4_sequence_patterns
            WHERE m4_intelligence_run_id = ? AND signature_sha256 = ?""",
            (m4_intelligence_run_id, signature_sha256),
        ).fetchone()
        if existing is not None:
            if str(existing["input_sha256"]) != input_sha256:
                raise RuntimeError("immutable M4 sequence pattern input changed")
            continue
        cursor = repository.connection.execute(
            """INSERT INTO m4_sequence_patterns
            (m4_intelligence_run_id, signature_json, signature_sha256, input_sha256,
             member_count, distinct_source_count, confidence, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
            (m4_intelligence_run_id, signature_json, signature_sha256, input_sha256,
             len(members), len(sources), "MEDIUM" if len(members) >= 3 else "LOW"),
        )
        if cursor.lastrowid is None:
            raise RuntimeError("SQLite did not return an M4 sequence pattern id")
        pattern_id = int(cursor.lastrowid)
        for ordinal, member in enumerate(sorted(members, key=lambda item: int(item["id"]))):
            repository.connection.execute(
                """INSERT INTO m4_sequence_pattern_members
                (m4_sequence_pattern_id, m4_intelligence_instance_id, ordinal)
                VALUES (?, ?, ?)""",
                (pattern_id, int(member["id"]), ordinal),
            )
        inserted += 1
    repository.connection.commit()
    return inserted


def derive_m4_instances(repository: Repository, m4_intelligence_run_id: int) -> int:
    """Derive one immutable M4 instance per pinned successful M1/M2 input."""
    run = repository.connection.execute(
        "SELECT * FROM m4_intelligence_runs WHERE id = ?", (m4_intelligence_run_id,)
    ).fetchone()
    if run is None:
        raise KeyError("M4 intelligence run not found")
    config = json.loads(str(run["config_json"]))
    required = {
        "analyzer_version", "taxonomy_version", "prompt_version", "model_provider",
        "model_name", "model_parameters", "first_line_extractor_version",
        "parent_ending_extractor_version",
    }
    if not isinstance(config, dict) or set(config) != required:
        raise ValueError("M4 intelligence config is incomplete")
    parameters = _canonical_json(config["model_parameters"])
    rows = repository.connection.execute(
        """SELECT analysis_runs.id AS analysis_run_id, analysis_runs.input_sha256,
                  dataset_members.normalized_post_version_id,
                  first_line_features.id AS first_line_feature_id,
                  first_line_features.feature_json AS first_line_json,
                  first_line_features.input_sha256 AS first_line_input_sha256,
                  first_line_features.feature_sha256 AS first_line_feature_sha256,
                  parent_ending_features.id AS parent_ending_feature_id,
                  parent_ending_features.feature_json AS parent_ending_json,
                  parent_ending_features.input_sha256 AS parent_ending_input_sha256,
                  parent_ending_features.feature_sha256 AS parent_ending_feature_sha256
           FROM dataset_members
           JOIN analysis_runs
             ON analysis_runs.normalized_post_version_id =
                dataset_members.normalized_post_version_id
           JOIN first_line_features ON first_line_features.analysis_run_row_id = analysis_runs.id
           JOIN parent_ending_features
             ON parent_ending_features.child_analysis_run_row_id = analysis_runs.id
           WHERE dataset_members.dataset_snapshot_id = ? AND analysis_runs.status = 'SUCCEEDED'
             AND analysis_runs.analyzer_version = ? AND analysis_runs.taxonomy_version = ?
             AND analysis_runs.prompt_version = ? AND analysis_runs.model_provider = ?
             AND analysis_runs.model_name = ? AND analysis_runs.model_parameters_json = ?
             AND first_line_features.extractor_version = ?
             AND parent_ending_features.extractor_version = ?
           ORDER BY dataset_members.ordinal, analysis_runs.id""",
        (run["dataset_snapshot_id"], config["analyzer_version"], config["taxonomy_version"],
         config["prompt_version"], config["model_provider"], config["model_name"], parameters,
         config["first_line_extractor_version"], config["parent_ending_extractor_version"]),
    ).fetchall()
    selected: Dict[int, Any] = {}
    for row in rows:
        selected.setdefault(int(row["normalized_post_version_id"]), row)
    for row in selected.values():
        first = json.loads(str(row["first_line_json"]))
        ending = json.loads(str(row["parent_ending_json"]))
        feature = build_intelligence_feature(first, ending)
        input_document = {
            "analysis_input_sha256": row["input_sha256"],
            "first_line_input_sha256": row["first_line_input_sha256"],
            "first_line_feature_sha256": row["first_line_feature_sha256"],
            "parent_ending_input_sha256": row["parent_ending_input_sha256"],
            "parent_ending_feature_sha256": row["parent_ending_feature_sha256"],
            "derivation_version": DERIVATION_VERSION,
        }
        repository.persist_m4_intelligence_instance(
            m4_intelligence_run_id=m4_intelligence_run_id,
            normalized_post_version_id=int(row["normalized_post_version_id"]),
            analysis_run_row_id=int(row["analysis_run_id"]),
            first_line_feature_id=int(row["first_line_feature_id"]),
            parent_ending_feature_id=int(row["parent_ending_feature_id"]),
            feature=feature,
            input_sha256=hashlib.sha256(_canonical_json(input_document).encode("utf-8")).hexdigest(),
        )
    return len(selected)
