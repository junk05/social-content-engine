"""SQLite implementation of the M0 repository boundary."""

import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from .browser_detail import (
    DETAIL_ATTEMPT_CONTRACT_VERSION,
    validate_detail_attempt_provenance,
    validate_detail_failure,
)
from .browser_observation import (
    BROWSER_NORMALIZER_VERSION,
    browser_normalized_payload,
    browser_observation_status,
    canonical_browser_normalized_payload,
    canonical_threads_post_url,
    validate_browser_observation,
)
from .browser_text_quality import (
    ASSESSOR_VERSION,
    INVALID_TEXT_DATE_METADATA,
    INVALID_TEXT_TOPIC_TAG_METADATA,
    TEXT_UNAVAILABLE,
    VALID_TEXT,
)

SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS collection_runs (
  id INTEGER PRIMARY KEY,
  source TEXT NOT NULL,
  endpoint TEXT NOT NULL,
  request_json TEXT NOT NULL,
  started_at TEXT NOT NULL,
  completed_at TEXT NOT NULL,
  http_status INTEGER NOT NULL,
  response_headers_json TEXT NOT NULL,
  raw_response BLOB NOT NULL,
  raw_response_sha256 TEXT NOT NULL,
  collector_version TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS raw_posts (
  id INTEGER PRIMARY KEY,
  collection_run_id INTEGER NOT NULL REFERENCES collection_runs(id),
  source TEXT NOT NULL,
  source_post_id TEXT NOT NULL,
  raw_json BLOB NOT NULL,
  raw_sha256 TEXT NOT NULL,
  retrieved_at TEXT NOT NULL,
  UNIQUE(collection_run_id, source, source_post_id, raw_sha256)
);
CREATE TABLE IF NOT EXISTS accounts (
  id INTEGER PRIMARY KEY,
  source TEXT NOT NULL,
  source_account_id TEXT,
  username TEXT,
  observed_at TEXT NOT NULL,
  UNIQUE(source, source_account_id),
  UNIQUE(source, username)
);
CREATE TABLE IF NOT EXISTS normalized_posts (
  id INTEGER PRIMARY KEY,
  source TEXT NOT NULL,
  source_post_id TEXT NOT NULL,
  author_id TEXT,
  username TEXT,
  text TEXT,
  permalink TEXT,
  published_at TEXT,
  media_type TEXT,
  raw_sha256 TEXT NOT NULL,
  normalized_at TEXT NOT NULL,
  UNIQUE(source, source_post_id)
);
CREATE TABLE IF NOT EXISTS thread_relationships (
  id INTEGER PRIMARY KEY,
  source TEXT NOT NULL,
  child_post_id TEXT NOT NULL,
  parent_post_id TEXT,
  root_post_id TEXT,
  relationship_type TEXT NOT NULL,
  observed_at TEXT NOT NULL,
  UNIQUE(source, child_post_id, parent_post_id, relationship_type)
);
CREATE TABLE IF NOT EXISTS analysis_runs (
  id INTEGER PRIMARY KEY,
  analysis_run_id TEXT NOT NULL UNIQUE,
  source TEXT NOT NULL,
  source_post_id TEXT NOT NULL,
  normalized_post_version INTEGER NOT NULL,
  analyzer_version TEXT NOT NULL,
  taxonomy_version TEXT NOT NULL,
  prompt_version TEXT NOT NULL,
  model_provider TEXT NOT NULL,
  model_name TEXT NOT NULL,
  model_parameters_json TEXT NOT NULL,
  input_sha256 TEXT NOT NULL,
  output_sha256 TEXT,
  analyzed_at TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('RUNNING', 'SUCCEEDED', 'FAILED')),
  error_code TEXT,
  FOREIGN KEY(source, source_post_id) REFERENCES normalized_posts(source, source_post_id)
);
CREATE TABLE IF NOT EXISTS post_analysis (
  id INTEGER PRIMARY KEY,
  analysis_run_row_id INTEGER NOT NULL UNIQUE REFERENCES analysis_runs(id),
  normalized_post_id INTEGER NOT NULL REFERENCES normalized_posts(id),
  payload_json TEXT NOT NULL,
  output_sha256 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS patterns (
  id INTEGER PRIMARY KEY,
  pattern_key TEXT NOT NULL UNIQUE,
  payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pattern_instances (
  id INTEGER PRIMARY KEY,
  pattern_id INTEGER NOT NULL REFERENCES patterns(id),
  source_post_id TEXT NOT NULL,
  analysis_run_id INTEGER NOT NULL REFERENCES analysis_runs(id)
);
"""

Migration = Tuple[int, str, Callable[[sqlite3.Connection], None]]
PATTERN_INSTANCE_INPUT_CONTRACT = "M2_PATTERN_INSTANCE_INPUT_V1"
PATTERN_SET_INPUT_CONTRACT = "M2_PATTERN_SET_INPUT_V1"


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _canonical_json(document: Dict[str, Any]) -> str:
    return json.dumps(
        document, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True
    )


def pattern_instance_input_sha256(
    *,
    analysis_input_sha256: str,
    first_line_input_sha256: str,
    first_line_feature_sha256: str,
    parent_ending_input_sha256: str,
    parent_ending_feature_sha256: str,
) -> str:
    """Hash the fixed M2 pattern-instance evidence envelope."""
    document = {
        "contract_version": PATTERN_INSTANCE_INPUT_CONTRACT,
        "analysis_input_sha256": analysis_input_sha256,
        "first_line_input_sha256": first_line_input_sha256,
        "first_line_feature_sha256": first_line_feature_sha256,
        "parent_ending_input_sha256": parent_ending_input_sha256,
        "parent_ending_feature_sha256": parent_ending_feature_sha256,
    }
    return hashlib.sha256(_canonical_json(document).encode("utf-8")).hexdigest()


def pattern_set_input_sha256(
    instance_input_sha256s: Sequence[str], feature_signature: Dict[str, Any]
) -> str:
    """Hash an order-independent set of instance evidence for pattern provenance."""
    signature_json = _canonical_json(feature_signature)
    document = {
        "contract_version": PATTERN_SET_INPUT_CONTRACT,
        "feature_signature_sha256": hashlib.sha256(signature_json.encode("utf-8")).hexdigest(),
        "instance_input_sha256s": sorted(instance_input_sha256s),
    }
    return hashlib.sha256(_canonical_json(document).encode("utf-8")).hexdigest()


def _canonical_normalized_payload(post: Dict[str, Any]) -> Dict[str, Any]:
    """Return normalized content fields; observation time is version metadata."""
    return {
        "schema_version": int(post.get("schema_version", 1)),
        "source": post["source"],
        "source_post_id": post["source_post_id"],
        "author_id": post.get("author_id"),
        "username": post.get("username"),
        "text": post.get("text"),
        "permalink": post.get("permalink"),
        "published_at": post.get("published_at"),
        "media_type": post.get("media_type"),
        "raw_sha256": post["raw_sha256"],
    }


_PATTERN_FORBIDDEN_KEYS = {
    "text",
    "quote",
    "source_text",
    "line_text",
    "permalink",
    "username",
    "author_id",
    "account_id",
    "summary",
    "description",
}


def _is_contract_identifier(value: Any) -> bool:
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:-"
    return (
        isinstance(value, str)
        and 0 < len(value) <= 128
        and all(character in allowed for character in value)
    )


def _reject_pattern_leakage(value: Any) -> None:
    if isinstance(value, dict):
        if _PATTERN_FORBIDDEN_KEYS.intersection(value):
            raise ValueError("pattern artifacts must not persist source text or identity")
        for child in value.values():
            _reject_pattern_leakage(child)
    elif isinstance(value, list):
        for child in value:
            _reject_pattern_leakage(child)


def _validate_pattern_signature(signature: Dict[str, Any]) -> None:
    required = {
        "first_line_hook_family",
        "first_line_hook_subtype",
        "parent_ending_availability",
        "parent_cliffhanger_technique",
    }
    if set(signature) != required:
        raise ValueError("pattern feature signature does not match the closed contract")
    if signature["first_line_hook_family"] not in {
        "EMPTY",
        "QUESTION",
        "CONTRARIAN",
        "TARGETED",
        "EMOTIONAL",
        "OPEN_LOOP",
        "STATEMENT",
    }:
        raise ValueError("invalid pattern first-line hook family")
    if signature["first_line_hook_subtype"] not in {
        "EMPTY",
        "WHY_QUESTION",
        "DIRECT_QUESTION",
        "CONTRARIAN_ASSERTION",
        "AUDIENCE_CALL_OUT",
        "EMOTION_LED",
        "CONTINUATION_CUE",
        "PLAIN_STATEMENT",
    }:
        raise ValueError("invalid pattern first-line hook subtype")
    if signature["parent_ending_availability"] not in {
        "OBSERVED",
        "NO_PARENT",
        "PARENT_TEXT_UNAVAILABLE",
        "RELATIONSHIP_AMBIGUOUS",
    }:
        raise ValueError("invalid pattern parent-ending availability")
    if signature["parent_cliffhanger_technique"] not in {
        "UNKNOWN",
        "EXPLICIT_CONTINUATION",
        "ELLIPSIS",
        "UNANSWERED_QUESTION",
        "COLON_LEAD_IN",
        "NONE",
    }:
        raise ValueError("invalid pattern parent cliffhanger technique")


def _validate_pattern_ranking(ranking: Dict[str, Any]) -> None:
    if set(ranking) != {"method", "score", "rank"}:
        raise ValueError("pattern ranking does not match the closed contract")
    if not _is_contract_identifier(ranking["method"]):
        raise ValueError("pattern ranking method is required")
    score = ranking["score"]
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        raise ValueError("pattern ranking score must be numeric")
    rank = ranking["rank"]
    if isinstance(rank, bool) or not isinstance(rank, int) or rank < 1:
        raise ValueError("pattern rank must be a positive integer")


def _validate_pattern_provenance(provenance: Dict[str, Any]) -> None:
    required = {
        "dataset_snapshot_id",
        "miner_version",
        "feature_contract_version",
        "input_sha256",
    }
    if set(provenance) != required:
        raise ValueError("pattern provenance does not match the closed contract")
    if not isinstance(provenance["dataset_snapshot_id"], int):
        raise ValueError("pattern provenance requires a dataset snapshot id")
    for key in ("miner_version", "feature_contract_version"):
        if not _is_contract_identifier(provenance[key]):
            raise ValueError("pattern provenance version is required")
    value = provenance["input_sha256"]
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError("pattern provenance input hash is invalid")


def _table_columns(connection: sqlite3.Connection, table: str) -> Dict[str, sqlite3.Row]:
    return {
        str(row["name"]): row
        for row in connection.execute("PRAGMA table_info(" + table + ")").fetchall()
    }


def _migration_1_activate_analyzer_tables(connection: sqlite3.Connection) -> None:
    """Convert empty M0 reserved analyzer tables to the M1 shape."""
    if "analysis_run_id" in _table_columns(connection, "analysis_runs"):
        return
    count = int(connection.execute("SELECT COUNT(*) FROM analysis_runs").fetchone()[0])
    if count:
        raise RuntimeError("legacy analysis_runs contains data; automatic migration refused")
    connection.execute("DROP TABLE post_analysis")
    connection.execute("DROP TABLE analysis_runs")
    connection.execute(
        """CREATE TABLE analysis_runs (
          id INTEGER PRIMARY KEY,
          analysis_run_id TEXT NOT NULL UNIQUE,
          source TEXT NOT NULL,
          source_post_id TEXT NOT NULL,
          normalized_post_version INTEGER NOT NULL,
          analyzer_version TEXT NOT NULL,
          taxonomy_version TEXT NOT NULL,
          prompt_version TEXT NOT NULL,
          model_provider TEXT NOT NULL,
          model_name TEXT NOT NULL,
          model_parameters_json TEXT NOT NULL,
          input_sha256 TEXT NOT NULL,
          output_sha256 TEXT,
          analyzed_at TEXT NOT NULL,
          status TEXT NOT NULL CHECK(status IN ('RUNNING', 'SUCCEEDED', 'FAILED')),
          error_code TEXT,
          FOREIGN KEY(source, source_post_id)
            REFERENCES normalized_posts(source, source_post_id)
        )"""
    )
    connection.execute(
        """CREATE TABLE post_analysis (
          id INTEGER PRIMARY KEY,
          analysis_run_row_id INTEGER NOT NULL UNIQUE REFERENCES analysis_runs(id),
          normalized_post_id INTEGER NOT NULL REFERENCES normalized_posts(id),
          payload_json TEXT NOT NULL,
          output_sha256 TEXT NOT NULL
        )"""
    )


def _migration_2_normalized_versions(connection: sqlite3.Connection) -> None:
    connection.execute(
        """CREATE TABLE normalized_post_versions (
          id INTEGER PRIMARY KEY,
          normalized_post_id INTEGER NOT NULL REFERENCES normalized_posts(id),
          version INTEGER NOT NULL,
          canonical_payload_json TEXT NOT NULL,
          payload_sha256 TEXT NOT NULL,
          source_raw_post_id INTEGER REFERENCES raw_posts(id),
          normalized_at TEXT NOT NULL,
          normalizer_version TEXT NOT NULL,
          UNIQUE(normalized_post_id, version),
          UNIQUE(normalized_post_id, payload_sha256)
        )"""
    )
    if "current_version_id" not in _table_columns(connection, "normalized_posts"):
        connection.execute(
            "ALTER TABLE normalized_posts ADD COLUMN current_version_id INTEGER "
            "REFERENCES normalized_post_versions(id)"
        )
    posts = connection.execute("SELECT * FROM normalized_posts ORDER BY id").fetchall()
    for row in posts:
        post = dict(row)
        payload_json = _canonical_json(_canonical_normalized_payload(post))
        payload_sha256 = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
        raw = connection.execute(
            """SELECT id FROM raw_posts
            WHERE source = ? AND source_post_id = ? AND raw_sha256 = ?
            ORDER BY id DESC LIMIT 1""",
            (post["source"], post["source_post_id"], post["raw_sha256"]),
        ).fetchone()
        cursor = connection.execute(
            """INSERT INTO normalized_post_versions
            (normalized_post_id, version, canonical_payload_json, payload_sha256,
             source_raw_post_id, normalized_at, normalizer_version)
            VALUES (?, 1, ?, ?, ?, ?, 'm0-normalizer-v1')""",
            (
                post["id"],
                payload_json,
                payload_sha256,
                int(raw["id"]) if raw is not None else None,
                post["normalized_at"],
            ),
        )
        if cursor.lastrowid is None:
            raise RuntimeError("SQLite did not return a normalized post version id")
        connection.execute(
            "UPDATE normalized_posts SET current_version_id = ? WHERE id = ?",
            (int(cursor.lastrowid), post["id"]),
        )
    if "normalized_post_version_id" not in _table_columns(connection, "analysis_runs"):
        connection.execute(
            "ALTER TABLE analysis_runs ADD COLUMN normalized_post_version_id INTEGER "
            "REFERENCES normalized_post_versions(id)"
        )
    connection.execute(
        """UPDATE analysis_runs
        SET normalized_post_version_id = (
          SELECT normalized_post_versions.id
          FROM normalized_posts
          JOIN normalized_post_versions
            ON normalized_post_versions.normalized_post_id = normalized_posts.id
          WHERE normalized_posts.source = analysis_runs.source
            AND normalized_posts.source_post_id = analysis_runs.source_post_id
            AND normalized_post_versions.version = analysis_runs.normalized_post_version
        )
        WHERE normalized_post_version_id IS NULL"""
    )
    missing = int(
        connection.execute(
            "SELECT COUNT(*) FROM analysis_runs WHERE normalized_post_version_id IS NULL"
        ).fetchone()[0]
    )
    if missing:
        raise RuntimeError("analysis run could not be linked to a normalized post version")


def _migration_3_dataset_expansion(connection: sqlite3.Connection) -> None:
    connection.execute(
        """CREATE TABLE collection_batches (
          id INTEGER PRIMARY KEY,
          batch_key TEXT NOT NULL UNIQUE,
          status TEXT NOT NULL CHECK(status IN ('RUNNING', 'COMPLETE', 'FAILED')),
          config_json TEXT NOT NULL,
          config_sha256 TEXT NOT NULL,
          started_at TEXT NOT NULL,
          completed_at TEXT,
          collector_version TEXT NOT NULL
        )"""
    )
    connection.execute(
        """CREATE TABLE collection_batch_queries (
          id INTEGER PRIMARY KEY,
          collection_batch_id INTEGER NOT NULL REFERENCES collection_batches(id),
          ordinal INTEGER NOT NULL CHECK(ordinal >= 0),
          query_json TEXT NOT NULL,
          query_sha256 TEXT NOT NULL,
          UNIQUE(collection_batch_id, ordinal),
          UNIQUE(collection_batch_id, query_sha256)
        )"""
    )
    connection.execute(
        """CREATE TABLE collection_batch_runs (
          id INTEGER PRIMARY KEY,
          collection_batch_query_id INTEGER NOT NULL REFERENCES collection_batch_queries(id),
          collection_run_id INTEGER NOT NULL UNIQUE REFERENCES collection_runs(id)
        )"""
    )
    connection.execute(
        """CREATE TABLE dataset_snapshots (
          id INTEGER PRIMARY KEY,
          dataset_key TEXT NOT NULL,
          version INTEGER NOT NULL CHECK(version >= 1),
          status TEXT NOT NULL CHECK(status IN ('DRAFT', 'FINALIZED')),
          selection_spec_json TEXT NOT NULL,
          selection_spec_sha256 TEXT NOT NULL,
          created_at TEXT NOT NULL,
          finalized_at TEXT,
          UNIQUE(dataset_key, version)
        )"""
    )
    connection.execute(
        """CREATE TABLE dataset_members (
          id INTEGER PRIMARY KEY,
          dataset_snapshot_id INTEGER NOT NULL REFERENCES dataset_snapshots(id),
          normalized_post_version_id INTEGER NOT NULL REFERENCES normalized_post_versions(id),
          selected_raw_post_id INTEGER NOT NULL REFERENCES raw_posts(id),
          ordinal INTEGER NOT NULL CHECK(ordinal >= 0),
          inclusion_reason_json TEXT NOT NULL,
          UNIQUE(dataset_snapshot_id, normalized_post_version_id),
          UNIQUE(dataset_snapshot_id, ordinal)
        )"""
    )
    connection.execute(
        """CREATE TABLE post_metric_observations (
          id INTEGER PRIMARY KEY,
          source TEXT NOT NULL,
          source_post_id TEXT NOT NULL,
          metric_name TEXT NOT NULL,
          metric_value INTEGER NOT NULL CHECK(
            typeof(metric_value) = 'integer' AND metric_value >= 0
          ),
          observed_at TEXT NOT NULL,
          raw_post_id INTEGER REFERENCES raw_posts(id),
          collection_run_id INTEGER REFERENCES collection_runs(id),
          api_field TEXT NOT NULL,
          unit TEXT NOT NULL,
          collector_version TEXT NOT NULL,
          CHECK(raw_post_id IS NOT NULL OR collection_run_id IS NOT NULL),
          FOREIGN KEY(source, source_post_id)
            REFERENCES normalized_posts(source, source_post_id)
        )"""
    )
    connection.execute(
        """CREATE TRIGGER dataset_member_insert_requires_draft
        BEFORE INSERT ON dataset_members
        WHEN (SELECT status FROM dataset_snapshots WHERE id = NEW.dataset_snapshot_id)
             != 'DRAFT'
        BEGIN SELECT RAISE(ABORT, 'finalized dataset snapshot is immutable'); END"""
    )
    connection.execute(
        """CREATE TRIGGER finalized_dataset_member_update_forbidden
        BEFORE UPDATE ON dataset_members
        WHEN (SELECT status FROM dataset_snapshots WHERE id = OLD.dataset_snapshot_id)
             = 'FINALIZED'
        BEGIN SELECT RAISE(ABORT, 'finalized dataset snapshot is immutable'); END"""
    )
    connection.execute(
        """CREATE TRIGGER finalized_dataset_member_delete_forbidden
        BEFORE DELETE ON dataset_members
        WHEN (SELECT status FROM dataset_snapshots WHERE id = OLD.dataset_snapshot_id)
             = 'FINALIZED'
        BEGIN SELECT RAISE(ABORT, 'finalized dataset snapshot is immutable'); END"""
    )
    connection.execute(
        """CREATE TRIGGER finalized_dataset_snapshot_update_forbidden
        BEFORE UPDATE ON dataset_snapshots
        WHEN OLD.status = 'FINALIZED'
        BEGIN SELECT RAISE(ABORT, 'finalized dataset snapshot is immutable'); END"""
    )
    connection.execute(
        """CREATE TRIGGER finalized_dataset_snapshot_delete_forbidden
        BEFORE DELETE ON dataset_snapshots
        WHEN OLD.status = 'FINALIZED'
        BEGIN SELECT RAISE(ABORT, 'finalized dataset snapshot is immutable'); END"""
    )


def _migration_4_analysis_batches(connection: sqlite3.Connection) -> None:
    connection.execute(
        """CREATE TABLE analysis_batches (
          id INTEGER PRIMARY KEY,
          batch_key TEXT NOT NULL UNIQUE,
          dataset_snapshot_id INTEGER NOT NULL REFERENCES dataset_snapshots(id),
          analyzer_version TEXT NOT NULL,
          taxonomy_version TEXT NOT NULL,
          prompt_version TEXT NOT NULL,
          model_provider TEXT NOT NULL,
          model_name TEXT NOT NULL,
          model_parameters_json TEXT NOT NULL,
          config_sha256 TEXT NOT NULL,
          status TEXT NOT NULL CHECK(status IN ('RUNNING', 'SUCCEEDED', 'PARTIAL_FAILED')),
          started_at TEXT NOT NULL,
          completed_at TEXT
        )"""
    )
    connection.execute(
        """CREATE TABLE analysis_batch_items (
          id INTEGER PRIMARY KEY,
          analysis_batch_id INTEGER NOT NULL REFERENCES analysis_batches(id),
          normalized_post_version_id INTEGER NOT NULL REFERENCES normalized_post_versions(id),
          status TEXT NOT NULL CHECK(status IN ('PENDING', 'RUNNING', 'SUCCEEDED', 'FAILED')),
          analysis_run_row_id INTEGER REFERENCES analysis_runs(id),
          error_code TEXT,
          attempt INTEGER NOT NULL DEFAULT 0 CHECK(attempt >= 0),
          started_at TEXT,
          completed_at TEXT,
          UNIQUE(analysis_batch_id, normalized_post_version_id)
        )"""
    )


def _migration_5_first_line_features(connection: sqlite3.Connection) -> None:
    connection.execute(
        """CREATE TABLE first_line_features (
          id INTEGER PRIMARY KEY,
          analysis_run_row_id INTEGER NOT NULL REFERENCES analysis_runs(id),
          normalized_post_version_id INTEGER NOT NULL REFERENCES normalized_post_versions(id),
          extractor_version TEXT NOT NULL,
          feature_contract_version TEXT NOT NULL,
          input_sha256 TEXT NOT NULL,
          feature_json TEXT NOT NULL,
          feature_sha256 TEXT NOT NULL,
          extracted_at TEXT NOT NULL,
          UNIQUE(analysis_run_row_id, extractor_version)
        )"""
    )


def _migration_6_parent_ending_features(connection: sqlite3.Connection) -> None:
    connection.execute(
        """CREATE TABLE parent_ending_features (
          id INTEGER PRIMARY KEY,
          child_analysis_run_row_id INTEGER NOT NULL REFERENCES analysis_runs(id),
          child_normalized_post_version_id INTEGER NOT NULL REFERENCES normalized_post_versions(id),
          parent_normalized_post_version_id INTEGER REFERENCES normalized_post_versions(id),
          parent_analysis_run_row_id INTEGER REFERENCES analysis_runs(id),
          extractor_version TEXT NOT NULL,
          feature_contract_version TEXT NOT NULL,
          input_sha256 TEXT NOT NULL,
          feature_json TEXT NOT NULL,
          feature_sha256 TEXT NOT NULL,
          extracted_at TEXT NOT NULL,
          UNIQUE(child_analysis_run_row_id, extractor_version)
        )"""
    )


def _migration_7_pattern_evidence_contract(connection: sqlite3.Connection) -> None:
    legacy_patterns = int(connection.execute("SELECT COUNT(*) FROM patterns").fetchone()[0])
    legacy_instances = int(
        connection.execute("SELECT COUNT(*) FROM pattern_instances").fetchone()[0]
    )
    if legacy_patterns or legacy_instances:
        raise RuntimeError("legacy pattern tables contain unversioned data; migration refused")
    connection.execute("DROP TABLE pattern_instances")
    connection.execute("DROP TABLE patterns")
    connection.execute(
        """CREATE TABLE patterns (
          id INTEGER PRIMARY KEY,
          pattern_key TEXT NOT NULL,
          version INTEGER NOT NULL CHECK(version >= 1),
          feature_signature_json TEXT NOT NULL,
          feature_signature_sha256 TEXT NOT NULL,
          member_count INTEGER NOT NULL CHECK(member_count >= 2),
          ranking_json TEXT NOT NULL,
          provenance_json TEXT NOT NULL,
          review_status TEXT NOT NULL
            CHECK(review_status IN ('PENDING', 'APPROVED', 'REJECTED')),
          created_at TEXT NOT NULL,
          UNIQUE(pattern_key, version)
        )"""
    )
    connection.execute(
        """CREATE TABLE pattern_instances (
          id INTEGER PRIMARY KEY,
          pattern_id INTEGER NOT NULL REFERENCES patterns(id),
          source TEXT NOT NULL,
          source_post_id TEXT NOT NULL,
          analysis_run_row_id INTEGER NOT NULL REFERENCES analysis_runs(id),
          normalized_post_version_id INTEGER NOT NULL REFERENCES normalized_post_versions(id),
          normalized_version INTEGER NOT NULL CHECK(normalized_version >= 1),
          first_line_feature_id INTEGER NOT NULL REFERENCES first_line_features(id),
          parent_ending_feature_id INTEGER NOT NULL REFERENCES parent_ending_features(id),
          extractor_version TEXT NOT NULL,
          feature_contract_version TEXT NOT NULL,
          input_sha256 TEXT NOT NULL,
          feature_json TEXT NOT NULL,
          feature_sha256 TEXT NOT NULL,
          created_at TEXT NOT NULL,
          FOREIGN KEY(source, source_post_id)
            REFERENCES normalized_posts(source, source_post_id),
          UNIQUE(pattern_id, source, source_post_id),
          UNIQUE(pattern_id, analysis_run_row_id)
        )"""
    )


def _migration_8_browser_observations(connection: sqlite3.Connection) -> None:
    connection.execute(
        """CREATE TABLE browser_post_identities (
          id INTEGER PRIMARY KEY,
          source TEXT NOT NULL CHECK(source = 'threads'),
          post_url TEXT NOT NULL UNIQUE,
          source_post_id TEXT,
          status TEXT NOT NULL CHECK(status IN (
            'COLLECTED', 'DETAIL_PENDING', 'DETAIL_ENRICHED', 'DETAIL_FAILED'
          )),
          normalized_post_id INTEGER REFERENCES normalized_posts(id),
          current_observation_id INTEGER REFERENCES browser_observations(id),
          current_normalized_version_id INTEGER REFERENCES browser_normalized_versions(id),
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        )"""
    )
    connection.execute(
        """CREATE TABLE browser_observations (
          id INTEGER PRIMARY KEY,
          browser_post_identity_id INTEGER NOT NULL REFERENCES browser_post_identities(id),
          observation_type TEXT NOT NULL CHECK(observation_type IN ('SEARCH_CARD', 'POST_DETAIL')),
          source TEXT NOT NULL CHECK(source = 'threads'),
          post_url TEXT NOT NULL,
          source_post_id TEXT,
          status TEXT NOT NULL CHECK(status IN (
            'COLLECTED', 'DETAIL_PENDING', 'DETAIL_ENRICHED', 'DETAIL_FAILED'
          )),
          canonical_payload_json TEXT NOT NULL,
          payload_sha256 TEXT NOT NULL,
          field_provenance_json TEXT NOT NULL,
          field_provenance_sha256 TEXT NOT NULL,
          collection_context_json TEXT NOT NULL,
          collected_at TEXT NOT NULL,
          extractor_version TEXT NOT NULL
        )"""
    )
    connection.execute(
        """CREATE TABLE browser_observed_fields (
          id INTEGER PRIMARY KEY,
          browser_observation_id INTEGER NOT NULL REFERENCES browser_observations(id),
          field_name TEXT NOT NULL,
          observed_value_json TEXT NOT NULL,
          surface TEXT NOT NULL CHECK(surface IN (
            'threads_search_card', 'threads_post_detail'
          )),
          observed_at TEXT NOT NULL,
          extractor_version TEXT NOT NULL,
          UNIQUE(browser_observation_id, field_name)
        )"""
    )
    connection.execute(
        """CREATE TABLE browser_normalized_versions (
          id INTEGER PRIMARY KEY,
          browser_post_identity_id INTEGER NOT NULL REFERENCES browser_post_identities(id),
          version INTEGER NOT NULL CHECK(version >= 1),
          canonical_payload_json TEXT NOT NULL,
          payload_sha256 TEXT NOT NULL,
          source_observation_id INTEGER NOT NULL REFERENCES browser_observations(id),
          normalized_at TEXT NOT NULL,
          normalizer_version TEXT NOT NULL,
          UNIQUE(browser_post_identity_id, version),
          UNIQUE(browser_post_identity_id, payload_sha256)
        )"""
    )
    for table in (
        "browser_observations",
        "browser_observed_fields",
        "browser_normalized_versions",
    ):
        connection.execute(
            """CREATE TRIGGER immutable_{0}_update
            BEFORE UPDATE ON {0}
            BEGIN SELECT RAISE(ABORT, 'browser evidence is immutable'); END""".format(table)
        )
        connection.execute(
            """CREATE TRIGGER immutable_{0}_delete
            BEFORE DELETE ON {0}
            BEGIN SELECT RAISE(ABORT, 'browser evidence is immutable'); END""".format(table)
        )


def _migration_9_browser_detail_attempts(connection: sqlite3.Connection) -> None:
    connection.execute(
        """CREATE TABLE browser_detail_attempts (
          id INTEGER PRIMARY KEY,
          browser_post_identity_id INTEGER NOT NULL REFERENCES browser_post_identities(id),
          post_url TEXT NOT NULL,
          attempted_at TEXT NOT NULL,
          extractor_version TEXT NOT NULL,
          contract_version TEXT NOT NULL,
          outcome TEXT NOT NULL CHECK(outcome IN ('SUCCEEDED', 'FAILED')),
          detail_observation_id INTEGER REFERENCES browser_observations(id),
          CHECK(
            (outcome = 'SUCCEEDED' AND detail_observation_id IS NOT NULL)
            OR (outcome = 'FAILED' AND detail_observation_id IS NULL)
          )
        )"""
    )
    connection.execute(
        """CREATE TABLE browser_detail_failures (
          id INTEGER PRIMARY KEY,
          browser_detail_attempt_id INTEGER NOT NULL UNIQUE
            REFERENCES browser_detail_attempts(id),
          failure_type TEXT NOT NULL CHECK(failure_type IN (
            'NAVIGATION_FAILED', 'PAGE_UNAVAILABLE', 'EXTRACTION_FAILED',
            'VALIDATION_FAILED', 'TIMEOUT'
          )),
          failure_reason TEXT NOT NULL CHECK(failure_reason IN (
            'NETWORK_ERROR', 'POST_NOT_FOUND', 'LOGIN_REQUIRED',
            'EXPECTED_FIELD_MISSING', 'UNRECOGNIZED_PAGE',
            'INVALID_OBSERVATION', 'TIME_LIMIT_EXCEEDED'
          ))
        )"""
    )
    connection.execute(
        """CREATE TRIGGER validate_browser_detail_attempt_insert
        BEFORE INSERT ON browser_detail_attempts
        WHEN NEW.outcome = 'SUCCEEDED' AND NOT EXISTS (
          SELECT 1 FROM browser_observations
          WHERE id = NEW.detail_observation_id
            AND observation_type = 'POST_DETAIL'
            AND browser_post_identity_id = NEW.browser_post_identity_id
            AND post_url = NEW.post_url
        )
        BEGIN SELECT RAISE(ABORT, 'detail success must match POST_DETAIL evidence'); END"""
    )
    connection.execute(
        """CREATE TRIGGER validate_browser_detail_failure_insert
        BEFORE INSERT ON browser_detail_failures
        WHEN NOT EXISTS (
          SELECT 1 FROM browser_detail_attempts
          WHERE id = NEW.browser_detail_attempt_id AND outcome = 'FAILED'
        )
        BEGIN SELECT RAISE(ABORT, 'detail failure must match a failed attempt'); END"""
    )
    for table in ("browser_detail_attempts", "browser_detail_failures"):
        connection.execute(
            """CREATE TRIGGER immutable_{0}_update
            BEFORE UPDATE ON {0}
            BEGIN SELECT RAISE(ABORT, 'browser detail evidence is immutable'); END""".format(table)
        )
        connection.execute(
            """CREATE TRIGGER immutable_{0}_delete
            BEFORE DELETE ON {0}
            BEGIN SELECT RAISE(ABORT, 'browser detail evidence is immutable'); END""".format(table)
        )


def _migration_10_browser_normalized_bridge(connection: sqlite3.Connection) -> None:
    connection.execute(
        """CREATE TABLE browser_normalized_bridges (
          id INTEGER PRIMARY KEY,
          browser_post_identity_id INTEGER NOT NULL REFERENCES browser_post_identities(id),
          browser_normalized_version_id INTEGER NOT NULL UNIQUE
            REFERENCES browser_normalized_versions(id),
          normalized_post_id INTEGER NOT NULL REFERENCES normalized_posts(id),
          normalized_post_version_id INTEGER NOT NULL REFERENCES normalized_post_versions(id),
          bridged_at TEXT NOT NULL,
          bridge_version TEXT NOT NULL,
          UNIQUE(browser_normalized_version_id, normalized_post_version_id)
        )"""
    )
    connection.execute("DROP TRIGGER dataset_member_insert_requires_draft")
    connection.execute("DROP TRIGGER finalized_dataset_member_update_forbidden")
    connection.execute("DROP TRIGGER finalized_dataset_member_delete_forbidden")
    connection.execute("PRAGMA defer_foreign_keys = ON")
    connection.execute(
        """CREATE TABLE dataset_members_m3 (
          id INTEGER PRIMARY KEY,
          dataset_snapshot_id INTEGER NOT NULL REFERENCES dataset_snapshots(id),
          normalized_post_version_id INTEGER NOT NULL REFERENCES normalized_post_versions(id),
          selected_raw_post_id INTEGER REFERENCES raw_posts(id),
          selected_browser_observation_id INTEGER REFERENCES browser_observations(id),
          ordinal INTEGER NOT NULL CHECK(ordinal >= 0),
          inclusion_reason_json TEXT NOT NULL,
          CHECK((selected_raw_post_id IS NOT NULL) !=
                (selected_browser_observation_id IS NOT NULL)),
          UNIQUE(dataset_snapshot_id, normalized_post_version_id),
          UNIQUE(dataset_snapshot_id, ordinal)
        )"""
    )
    connection.execute(
        """INSERT INTO dataset_members_m3
        (id, dataset_snapshot_id, normalized_post_version_id, selected_raw_post_id,
         selected_browser_observation_id, ordinal, inclusion_reason_json)
        SELECT id, dataset_snapshot_id, normalized_post_version_id, selected_raw_post_id,
               NULL, ordinal, inclusion_reason_json FROM dataset_members"""
    )
    connection.execute("DROP TABLE dataset_members")
    connection.execute("ALTER TABLE dataset_members_m3 RENAME TO dataset_members")
    connection.execute(
        """CREATE TRIGGER dataset_member_insert_requires_draft
        BEFORE INSERT ON dataset_members
        WHEN (SELECT status FROM dataset_snapshots WHERE id = NEW.dataset_snapshot_id)
             != 'DRAFT'
        BEGIN SELECT RAISE(ABORT, 'finalized dataset snapshot is immutable'); END"""
    )
    connection.execute(
        """CREATE TRIGGER finalized_dataset_member_update_forbidden
        BEFORE UPDATE ON dataset_members
        WHEN (SELECT status FROM dataset_snapshots WHERE id = OLD.dataset_snapshot_id)
             = 'FINALIZED'
        BEGIN SELECT RAISE(ABORT, 'finalized dataset snapshot is immutable'); END"""
    )
    connection.execute(
        """CREATE TRIGGER finalized_dataset_member_delete_forbidden
        BEFORE DELETE ON dataset_members
        WHEN (SELECT status FROM dataset_snapshots WHERE id = OLD.dataset_snapshot_id)
             = 'FINALIZED'
        BEGIN SELECT RAISE(ABORT, 'finalized dataset snapshot is immutable'); END"""
    )


def _migration_11_m4_pattern_intelligence(connection: sqlite3.Connection) -> None:
    """Additive, text-free M4 run, instance, and metric-provenance storage."""
    connection.execute(
        """CREATE TABLE m4_intelligence_runs (
          id INTEGER PRIMARY KEY,
          dataset_snapshot_id INTEGER NOT NULL REFERENCES dataset_snapshots(id),
          taxonomy_version TEXT NOT NULL,
          derivation_version TEXT NOT NULL,
          config_json TEXT NOT NULL,
          config_sha256 TEXT NOT NULL,
          created_at TEXT NOT NULL,
          UNIQUE(dataset_snapshot_id, taxonomy_version, derivation_version, config_sha256)
        )"""
    )
    connection.execute(
        """CREATE TABLE m4_intelligence_instances (
          id INTEGER PRIMARY KEY,
          m4_intelligence_run_id INTEGER NOT NULL REFERENCES m4_intelligence_runs(id),
          normalized_post_version_id INTEGER NOT NULL REFERENCES normalized_post_versions(id),
          analysis_run_row_id INTEGER NOT NULL REFERENCES analysis_runs(id),
          first_line_feature_id INTEGER NOT NULL REFERENCES first_line_features(id),
          parent_ending_feature_id INTEGER NOT NULL REFERENCES parent_ending_features(id),
          feature_json TEXT NOT NULL,
          feature_sha256 TEXT NOT NULL,
          input_sha256 TEXT NOT NULL,
          created_at TEXT NOT NULL,
          UNIQUE(m4_intelligence_run_id, normalized_post_version_id)
        )"""
    )
    connection.execute(
        """CREATE TABLE m4_metric_snapshots (
          id INTEGER PRIMARY KEY,
          dataset_snapshot_id INTEGER NOT NULL REFERENCES dataset_snapshots(id),
          normalized_post_version_id INTEGER NOT NULL REFERENCES normalized_post_versions(id),
          browser_observation_id INTEGER NOT NULL REFERENCES browser_observations(id),
          field_name TEXT NOT NULL CHECK(field_name IN (
            'public_counters.view_count', 'public_counters.like_count',
            'public_counters.reply_count', 'public_counters.repost_count',
            'public_counters.quote_count', 'public_counters.share_count'
          )),
          metric_value INTEGER NOT NULL CHECK(metric_value >= 0),
          observed_at TEXT NOT NULL,
          surface TEXT NOT NULL CHECK(surface IN ('threads_search_card', 'threads_post_detail')),
          extractor_version TEXT NOT NULL,
          input_sha256 TEXT NOT NULL,
          metric_version TEXT NOT NULL,
          UNIQUE(dataset_snapshot_id, browser_observation_id, field_name)
        )"""
    )
    for table in ("m4_intelligence_instances", "m4_metric_snapshots"):
        connection.execute(
            """CREATE TRIGGER immutable_{0}_update BEFORE UPDATE ON {0}
            BEGIN SELECT RAISE(ABORT, 'M4 derived evidence is immutable'); END""".format(table)
        )
        connection.execute(
            """CREATE TRIGGER immutable_{0}_delete BEFORE DELETE ON {0}
            BEGIN SELECT RAISE(ABORT, 'M4 derived evidence is immutable'); END""".format(table)
        )


def _migration_12_m4_sequence_patterns(connection: sqlite3.Connection) -> None:
    """Persist only supported, text-free M4 sequence aggregates."""
    connection.execute(
        """CREATE TABLE m4_sequence_patterns (
          id INTEGER PRIMARY KEY,
          m4_intelligence_run_id INTEGER NOT NULL REFERENCES m4_intelligence_runs(id),
          signature_json TEXT NOT NULL,
          signature_sha256 TEXT NOT NULL,
          input_sha256 TEXT NOT NULL,
          member_count INTEGER NOT NULL CHECK(member_count >= 2),
          distinct_source_count INTEGER NOT NULL CHECK(distinct_source_count >= 2),
          confidence TEXT NOT NULL CHECK(confidence IN ('LOW', 'MEDIUM', 'HIGH')),
          created_at TEXT NOT NULL,
          UNIQUE(m4_intelligence_run_id, signature_sha256)
        )"""
    )
    connection.execute(
        """CREATE TABLE m4_sequence_pattern_members (
          m4_sequence_pattern_id INTEGER NOT NULL REFERENCES m4_sequence_patterns(id),
          m4_intelligence_instance_id INTEGER NOT NULL REFERENCES m4_intelligence_instances(id),
          ordinal INTEGER NOT NULL CHECK(ordinal >= 0),
          PRIMARY KEY(m4_sequence_pattern_id, m4_intelligence_instance_id),
          UNIQUE(m4_sequence_pattern_id, ordinal)
        )"""
    )
    for table in ("m4_sequence_patterns", "m4_sequence_pattern_members"):
        connection.execute(
            """CREATE TRIGGER immutable_{0}_update BEFORE UPDATE ON {0}
            BEGIN SELECT RAISE(ABORT, 'M4 sequence evidence is immutable'); END""".format(table)
        )
        connection.execute(
            """CREATE TRIGGER immutable_{0}_delete BEFORE DELETE ON {0}
            BEGIN SELECT RAISE(ABORT, 'M4 sequence evidence is immutable'); END""".format(table)
        )


def _migration_13_browser_thread_sequences(connection: sqlite3.Connection) -> None:
    """Append-only browser-detail sequence edges; no inferred relationships."""
    connection.execute(
        """CREATE TABLE browser_thread_sequence_observations (
          id INTEGER PRIMARY KEY,
          root_browser_post_identity_id INTEGER NOT NULL REFERENCES browser_post_identities(id),
          node_browser_post_identity_id INTEGER NOT NULL REFERENCES browser_post_identities(id),
          reply_to_browser_post_identity_id INTEGER REFERENCES browser_post_identities(id),
          sequence_position INTEGER NOT NULL CHECK(sequence_position >= 0),
          same_author_as_root INTEGER CHECK(same_author_as_root IN (0, 1)),
          detail_observation_id INTEGER NOT NULL REFERENCES browser_observations(id),
          observed_at TEXT NOT NULL,
          extractor_version TEXT NOT NULL,
          UNIQUE(detail_observation_id, node_browser_post_identity_id)
        )"""
    )
    connection.execute(
        """CREATE TRIGGER immutable_browser_thread_sequence_observations_update
        BEFORE UPDATE ON browser_thread_sequence_observations
        BEGIN SELECT RAISE(ABORT, 'browser thread sequence evidence is immutable'); END"""
    )
    connection.execute(
        """CREATE TRIGGER immutable_browser_thread_sequence_observations_delete
        BEFORE DELETE ON browser_thread_sequence_observations
        BEGIN SELECT RAISE(ABORT, 'browser thread sequence evidence is immutable'); END"""
    )


def _migration_23_thread_sequence_relationship_evidence(
    connection: sqlite3.Connection,
) -> None:
    columns = {
        str(row["name"])
        for row in connection.execute("PRAGMA table_info(browser_thread_sequence_observations)")
    }
    if "relationship_evidence" not in columns:
        connection.execute(
            """ALTER TABLE browser_thread_sequence_observations
            ADD COLUMN relationship_evidence TEXT CHECK(
              relationship_evidence IN (
                'ROOT_DETAIL_PAGE', 'DOM_CONTIGUOUS_ROOT_AUTHOR_CHAIN'
              )
            )"""
        )


def _migration_24_detail_enrichment_exclusions(connection: sqlite3.Connection) -> None:
    """Add reversible current exclusion state plus immutable human action history."""
    columns = {
        str(row["name"])
        for row in connection.execute("PRAGMA table_info(browser_detail_enrichment_queue)")
    }
    if "enrichment_excluded" not in columns:
        connection.execute(
            """ALTER TABLE browser_detail_enrichment_queue
            ADD COLUMN enrichment_excluded INTEGER NOT NULL DEFAULT 0
            CHECK(enrichment_excluded IN (0, 1))"""
        )
        connection.execute(
            """ALTER TABLE browser_detail_enrichment_queue
            ADD COLUMN exclusion_reason TEXT CHECK(
              exclusion_reason IS NULL
              OR exclusion_reason = 'USER_EXCLUDED_SOURCE_UNAVAILABLE'
            )"""
        )
        connection.execute(
            """ALTER TABLE browser_detail_enrichment_queue
            ADD COLUMN excluded_at TEXT"""
        )
    connection.execute(
        """CREATE TABLE browser_detail_enrichment_exclusion_actions (
          id INTEGER PRIMARY KEY,
          browser_detail_queue_id INTEGER NOT NULL
            REFERENCES browser_detail_enrichment_queue(id),
          action TEXT NOT NULL CHECK(action IN ('EXCLUDED', 'RE_ENABLED', 'REQUEUED')),
          exclusion_reason TEXT CHECK(
            (action = 'EXCLUDED'
             AND exclusion_reason = 'USER_EXCLUDED_SOURCE_UNAVAILABLE')
            OR (action != 'EXCLUDED' AND exclusion_reason IS NULL)
          ),
          acted_at TEXT NOT NULL
        )"""
    )
    for operation in ("UPDATE", "DELETE"):
        connection.execute(
            """CREATE TRIGGER immutable_browser_detail_enrichment_exclusion_actions_{0}
            BEFORE {1} ON browser_detail_enrichment_exclusion_actions
            BEGIN SELECT RAISE(ABORT, 'browser detail exclusion audit is immutable'); END""".format(
                operation.lower(), operation
            )
        )
    for operation in ("INSERT", "UPDATE"):
        connection.execute(
            """CREATE TRIGGER validate_browser_detail_enrichment_exclusion_{0}
            BEFORE {1} ON browser_detail_enrichment_queue
            WHEN (
              (NEW.enrichment_excluded = 1 AND (
                NEW.exclusion_reason != 'USER_EXCLUDED_SOURCE_UNAVAILABLE'
                OR NEW.exclusion_reason IS NULL OR NEW.excluded_at IS NULL
              ))
              OR (NEW.enrichment_excluded = 0 AND (
                NEW.exclusion_reason IS NOT NULL OR NEW.excluded_at IS NOT NULL
              ))
            )
            BEGIN SELECT RAISE(ABORT, 'invalid browser detail exclusion state'); END""".format(
                operation.lower(), operation
            )
        )


def _migration_25_topic_tag_text_quality(connection: sqlite3.Connection) -> None:
    """Allow evidence-confirmed topic metadata defects without rewriting history."""
    for operation in ("UPDATE", "DELETE"):
        connection.execute(
            "DROP TRIGGER IF EXISTS immutable_browser_text_quality_assessments_{0}".format(
                operation
            )
        )
    connection.execute(
        "ALTER TABLE browser_text_quality_assessments RENAME TO browser_text_quality_assessments_v1"
    )
    connection.execute(
        """CREATE TABLE browser_text_quality_assessments (
          id INTEGER PRIMARY KEY,
          browser_observation_id INTEGER NOT NULL
            REFERENCES browser_observations(id),
          quality_status TEXT NOT NULL CHECK(quality_status IN (
            'VALID_TEXT', 'INVALID_TEXT_DATE_METADATA',
            'INVALID_TEXT_TOPIC_TAG_METADATA', 'TEXT_UNAVAILABLE'
          )),
          assessor_version TEXT NOT NULL,
          input_sha256 TEXT NOT NULL,
          assessed_at TEXT NOT NULL
        )"""
    )
    connection.execute(
        "INSERT INTO browser_text_quality_assessments "
        "SELECT * FROM browser_text_quality_assessments_v1"
    )
    connection.execute("DROP TABLE browser_text_quality_assessments_v1")
    for operation in ("UPDATE", "DELETE"):
        connection.execute(
            """CREATE TRIGGER immutable_browser_text_quality_assessments_{0}
            BEFORE {0} ON browser_text_quality_assessments
            BEGIN SELECT RAISE(ABORT, 'browser text quality evidence is immutable'); END""".format(
                operation
            )
        )


def _migration_14_structural_pattern_extraction(connection: sqlite3.Connection) -> None:
    """Add append-only, source-text-free deterministic structural derivatives."""
    connection.execute(
        """CREATE TABLE structural_feature_runs (
          id INTEGER PRIMARY KEY,
          dataset_snapshot_id INTEGER NOT NULL REFERENCES dataset_snapshots(id),
          taxonomy_version TEXT NOT NULL,
          extractor_version TEXT NOT NULL,
          config_json TEXT NOT NULL,
          config_sha256 TEXT NOT NULL,
          created_at TEXT NOT NULL,
          UNIQUE(dataset_snapshot_id, taxonomy_version, extractor_version, config_sha256)
        )"""
    )
    connection.execute(
        """CREATE TABLE structural_feature_instances (
          id INTEGER PRIMARY KEY,
          structural_feature_run_id INTEGER NOT NULL REFERENCES structural_feature_runs(id),
          normalized_post_version_id INTEGER NOT NULL REFERENCES normalized_post_versions(id),
          feature_json TEXT NOT NULL,
          feature_sha256 TEXT NOT NULL,
          input_sha256 TEXT NOT NULL,
          created_at TEXT NOT NULL,
          UNIQUE(structural_feature_run_id, normalized_post_version_id)
        )"""
    )
    connection.execute(
        """CREATE TABLE structural_patterns (
          id INTEGER PRIMARY KEY,
          structural_feature_run_id INTEGER NOT NULL REFERENCES structural_feature_runs(id),
          pattern_kind TEXT NOT NULL CHECK(pattern_kind IN ('FIRST_LINE', 'POST', 'THREAD')),
          signature_json TEXT NOT NULL,
          signature_sha256 TEXT NOT NULL,
          input_sha256 TEXT NOT NULL,
          member_count INTEGER NOT NULL CHECK(member_count >= 2),
          distinct_source_count INTEGER NOT NULL CHECK(distinct_source_count >= 2),
          confidence TEXT NOT NULL CHECK(confidence IN ('LOW', 'MEDIUM', 'HIGH')),
          created_at TEXT NOT NULL,
          UNIQUE(structural_feature_run_id, pattern_kind, signature_sha256)
        )"""
    )
    connection.execute(
        """CREATE TABLE structural_pattern_members (
          structural_pattern_id INTEGER NOT NULL REFERENCES structural_patterns(id),
          structural_feature_instance_id INTEGER NOT NULL
            REFERENCES structural_feature_instances(id),
          ordinal INTEGER NOT NULL CHECK(ordinal >= 0),
          PRIMARY KEY(structural_pattern_id, structural_feature_instance_id),
          UNIQUE(structural_pattern_id, ordinal)
        )"""
    )
    for table in (
        "structural_feature_runs",
        "structural_feature_instances",
        "structural_patterns",
        "structural_pattern_members",
    ):
        connection.execute(
            """CREATE TRIGGER immutable_{0}_update BEFORE UPDATE ON {0}
            BEGIN SELECT RAISE(ABORT, 'structural evidence is immutable'); END""".format(table)
        )
        connection.execute(
            """CREATE TRIGGER immutable_{0}_delete BEFORE DELETE ON {0}
            BEGIN SELECT RAISE(ABORT, 'structural evidence is immutable'); END""".format(table)
        )


def _migration_15_browser_text_quality(connection: sqlite3.Connection) -> None:
    """Append deterministic quality assessments without mutating source evidence."""
    connection.execute(
        """CREATE TABLE browser_text_quality_assessments (
          id INTEGER PRIMARY KEY,
          browser_observation_id INTEGER NOT NULL UNIQUE
            REFERENCES browser_observations(id),
          quality_status TEXT NOT NULL CHECK(quality_status IN (
            'VALID_TEXT', 'INVALID_TEXT_DATE_METADATA', 'TEXT_UNAVAILABLE'
          )),
          assessor_version TEXT NOT NULL,
          input_sha256 TEXT NOT NULL,
          assessed_at TEXT NOT NULL
        )"""
    )
    for operation in ("UPDATE", "DELETE"):
        connection.execute(
            """CREATE TRIGGER immutable_browser_text_quality_assessments_{0}
            BEFORE {0} ON browser_text_quality_assessments
            BEGIN SELECT RAISE(ABORT, 'browser text quality evidence is immutable'); END""".format(
                operation
            )
        )


def _migration_16_detail_enrichment_queue(connection: sqlite3.Connection) -> None:
    """Add the durable, retryable M4 detail-enrichment work state."""
    connection.execute(
        """CREATE TABLE browser_detail_enrichment_batches (
          id INTEGER PRIMARY KEY,
          status TEXT NOT NULL CHECK(status IN ('RUNNING', 'COMPLETED', 'STOPPED')),
          requested_items INTEGER NOT NULL CHECK(requested_items >= 1),
          max_items INTEGER NOT NULL CHECK(max_items >= 1),
          started_at TEXT NOT NULL,
          completed_at TEXT
        )"""
    )
    connection.execute(
        """CREATE TABLE browser_detail_enrichment_queue (
          id INTEGER PRIMARY KEY,
          browser_post_identity_id INTEGER NOT NULL UNIQUE
            REFERENCES browser_post_identities(id),
          source_observation_id INTEGER NOT NULL REFERENCES browser_observations(id),
          status TEXT NOT NULL CHECK(status IN (
            'DETAIL_PENDING', 'DETAIL_PROCESSING', 'DETAIL_ENRICHED', 'DETAIL_FAILED'
          )),
          attempt_count INTEGER NOT NULL DEFAULT 0 CHECK(attempt_count >= 0),
          retry_count INTEGER NOT NULL DEFAULT 0 CHECK(retry_count >= 0),
          active_batch_id INTEGER REFERENCES browser_detail_enrichment_batches(id),
          lease_version INTEGER NOT NULL DEFAULT 0 CHECK(lease_version >= 0),
          last_attempt_id INTEGER REFERENCES browser_detail_attempts(id),
          last_error_code TEXT CHECK(last_error_code IN (
            'PAGE_TIMEOUT', 'POST_NOT_FOUND', 'ACTIVITY_BUTTON_NOT_FOUND',
            'ACTIVITY_DIALOG_TIMEOUT', 'VIEW_COUNT_NOT_FOUND',
            'THREAD_SEQUENCE_NOT_OBSERVED', 'INGESTION_FAILED', 'EXTRACTOR_MISMATCH'
          )),
          last_error_type TEXT CHECK(last_error_type IN (
            'NAVIGATION_FAILED', 'PAGE_UNAVAILABLE', 'EXTRACTION_FAILED',
            'VALIDATION_FAILED', 'TIMEOUT'
          )),
          last_error_reason TEXT CHECK(last_error_reason IN (
            'NETWORK_ERROR', 'POST_NOT_FOUND', 'LOGIN_REQUIRED',
            'EXPECTED_FIELD_MISSING', 'UNRECOGNIZED_PAGE',
            'INVALID_OBSERVATION', 'TIME_LIMIT_EXCEEDED'
          )),
          enqueued_at TEXT NOT NULL,
          claimed_at TEXT,
          updated_at TEXT NOT NULL,
          CHECK(
            (status = 'DETAIL_FAILED' AND last_error_code IS NOT NULL
             AND last_error_type IS NOT NULL AND last_error_reason IS NOT NULL)
            OR (status != 'DETAIL_FAILED' AND last_error_code IS NULL
                AND last_error_type IS NULL AND last_error_reason IS NULL)
          ),
          CHECK((status = 'DETAIL_PROCESSING') = (claimed_at IS NOT NULL))
        )"""
    )


def _migration_17_one_running_detail_batch(connection: sqlite3.Connection) -> None:
    """Make the durable Source Store authoritative for the single batch worker."""
    running = connection.execute(
        """SELECT id, started_at FROM browser_detail_enrichment_batches
        WHERE status = 'RUNNING' ORDER BY id"""
    ).fetchall()
    for stale in running[1:]:
        connection.execute(
            """UPDATE browser_detail_enrichment_queue SET
            status = 'DETAIL_PENDING', active_batch_id = NULL, claimed_at = NULL,
            last_error_code = NULL, last_error_type = NULL, last_error_reason = NULL,
            updated_at = ? WHERE active_batch_id = ? AND status IN (
              'DETAIL_PENDING', 'DETAIL_PROCESSING'
            )""",
            (stale["started_at"], stale["id"]),
        )
        connection.execute(
            """UPDATE browser_detail_enrichment_batches
            SET status = 'STOPPED', completed_at = started_at WHERE id = ?""",
            (stale["id"],),
        )
    connection.execute(
        """CREATE UNIQUE INDEX one_running_browser_detail_batch
        ON browser_detail_enrichment_batches(status) WHERE status = 'RUNNING'"""
    )


def _migration_18_backfill_selected_detail_queue(connection: sqlite3.Connection) -> None:
    """Queue existing human-selected pending identities without changing observations."""
    connection.execute(
        """INSERT OR IGNORE INTO browser_detail_enrichment_queue
        (browser_post_identity_id, source_observation_id, status, enqueued_at, updated_at)
        SELECT browser_post_identities.id,
               browser_post_identities.current_observation_id,
               'DETAIL_PENDING',
               browser_post_identities.updated_at,
               browser_post_identities.updated_at
        FROM browser_post_identities
        JOIN browser_observations
          ON browser_observations.id = browser_post_identities.current_observation_id
         AND browser_observations.browser_post_identity_id = browser_post_identities.id
        WHERE browser_post_identities.status = 'DETAIL_PENDING'
          AND browser_post_identities.current_observation_id IS NOT NULL"""
    )


def _migration_19_browser_metric_observation_statuses(
    connection: sqlite3.Connection,
) -> None:
    """Persist field-specific metric availability independently from detail success."""
    connection.execute(
        """CREATE TABLE browser_metric_observation_statuses (
          id INTEGER PRIMARY KEY,
          browser_observation_id INTEGER NOT NULL REFERENCES browser_observations(id),
          field_name TEXT NOT NULL CHECK(field_name IN (
            'public_counters.view_count', 'public_counters.like_count',
            'public_counters.reply_count', 'public_counters.repost_count',
            'public_counters.quote_count', 'public_counters.share_count'
          )),
          observation_status TEXT NOT NULL CHECK(observation_status IN (
            'OBSERVED', 'NOT_PRESENT', 'NOT_OBSERVED', 'EXTRACTION_FAILED'
          )),
          surface TEXT NOT NULL CHECK(surface = 'threads_post_detail'),
          observed_at TEXT NOT NULL,
          extractor_version TEXT NOT NULL,
          UNIQUE(browser_observation_id, field_name)
        )"""
    )
    for operation in ("UPDATE", "DELETE"):
        connection.execute(
            """CREATE TRIGGER immutable_browser_metric_observation_statuses_{0}
            BEFORE {0} ON browser_metric_observation_statuses
            BEGIN SELECT RAISE(ABORT, 'browser metric status evidence is immutable'); END""".format(
                operation.lower()
            )
        )


def _migration_20_browser_approximate_view_observations(
    connection: sqlite3.Connection,
) -> None:
    """Store replayable rounded detail-page Views apart from exact counters."""
    connection.execute(
        """CREATE TABLE browser_approximate_view_observations (
          id INTEGER PRIMARY KEY,
          browser_observation_id INTEGER NOT NULL UNIQUE REFERENCES browser_observations(id),
          display TEXT NOT NULL,
          normalized_approx INTEGER NOT NULL CHECK(normalized_approx >= 0),
          precision TEXT NOT NULL CHECK(precision = 'ROUNDED'),
          source TEXT NOT NULL CHECK(source = 'POST_DETAIL_PAGE'),
          view_band TEXT NOT NULL CHECK(view_band IN (
            'LT_1K', '1K_10K', '10K_100K', '100K_1M', '1M_PLUS'
          )),
          observed_at TEXT NOT NULL,
          extractor_version TEXT NOT NULL,
          normalizer_version TEXT NOT NULL
        )"""
    )
    for operation in ("UPDATE", "DELETE"):
        connection.execute(
            """CREATE TRIGGER immutable_browser_approximate_view_observations_{0}
            BEFORE {0} ON browser_approximate_view_observations
            BEGIN SELECT RAISE(
              ABORT, 'browser approximate Views evidence is immutable'
            ); END""".format(operation.lower())
        )


def _migration_21_detail_batch_assignment_history(connection: sqlite3.Connection) -> None:
    """Preserve immutable queue-to-batch assignment provenance across safe refreshes."""
    connection.execute(
        """CREATE TABLE browser_detail_batch_assignments (
          id INTEGER PRIMARY KEY,
          browser_detail_batch_id INTEGER NOT NULL
            REFERENCES browser_detail_enrichment_batches(id),
          browser_detail_queue_id INTEGER NOT NULL
            REFERENCES browser_detail_enrichment_queue(id),
          attempt_count INTEGER NOT NULL CHECK(attempt_count >= 1),
          lease_version INTEGER NOT NULL CHECK(lease_version >= 1),
          assigned_at TEXT NOT NULL,
          UNIQUE(browser_detail_batch_id, browser_detail_queue_id, attempt_count)
        )"""
    )
    connection.execute(
        """INSERT INTO browser_detail_batch_assignments
        (browser_detail_batch_id, browser_detail_queue_id, attempt_count,
         lease_version, assigned_at)
        SELECT active_batch_id, id, attempt_count, lease_version,
               COALESCE(claimed_at, updated_at)
        FROM browser_detail_enrichment_queue
        WHERE active_batch_id IS NOT NULL AND attempt_count >= 1"""
    )
    for operation in ("UPDATE", "DELETE"):
        connection.execute(
            """CREATE TRIGGER immutable_browser_detail_batch_assignments_{0}
            BEFORE {0} ON browser_detail_batch_assignments
            BEGIN SELECT RAISE(
              ABORT, 'browser detail batch assignment evidence is immutable'
            ); END""".format(operation.lower())
        )


def _migration_22_reconcile_detail_batch_assignments(connection: sqlite3.Connection) -> None:
    """Backfill assignments produced by a pre-migration receiver still finishing work."""
    connection.execute(
        """INSERT OR IGNORE INTO browser_detail_batch_assignments
        (browser_detail_batch_id, browser_detail_queue_id, attempt_count,
         lease_version, assigned_at)
        SELECT active_batch_id, id, attempt_count, lease_version,
               COALESCE(claimed_at, updated_at)
        FROM browser_detail_enrichment_queue
        WHERE active_batch_id IS NOT NULL AND attempt_count >= 1"""
    )


def _migration_26_browser_display_view_observations(
    connection: sqlite3.Connection,
) -> None:
    """Store exact integer Views displays without relabelling them API counters."""
    connection.execute(
        """CREATE TABLE browser_display_view_observations (
          id INTEGER PRIMARY KEY,
          browser_observation_id INTEGER NOT NULL UNIQUE REFERENCES browser_observations(id),
          display TEXT NOT NULL,
          normalized_value INTEGER NOT NULL CHECK(normalized_value >= 0),
          precision TEXT NOT NULL CHECK(precision = 'DISPLAY_EXACT'),
          source TEXT NOT NULL CHECK(source = 'POST_DETAIL_PAGE'),
          view_band TEXT NOT NULL CHECK(view_band IN (
            'LT_1K', '1K_10K', '10K_100K', '100K_1M', '1M_PLUS'
          )),
          observed_at TEXT NOT NULL,
          extractor_version TEXT NOT NULL,
          normalizer_version TEXT NOT NULL
        )"""
    )
    for operation in ("UPDATE", "DELETE"):
        connection.execute(
            """CREATE TRIGGER immutable_browser_display_view_observations_{0}
            BEFORE {0} ON browser_display_view_observations
            BEGIN SELECT RAISE(
              ABORT, 'browser display Views evidence is immutable'
            ); END""".format(operation.lower())
        )


MIGRATIONS: Tuple[Migration, ...] = (
    (1, "activate-m1-analyzer-tables-v1", _migration_1_activate_analyzer_tables),
    (2, "normalized-post-version-history-v1", _migration_2_normalized_versions),
    (3, "collection-batches-datasets-metric-observations-v1", _migration_3_dataset_expansion),
    (4, "analysis-batches-pinned-dataset-versions-v1", _migration_4_analysis_batches),
    (5, "first-line-features-no-source-text-v1", _migration_5_first_line_features),
    (6, "parent-ending-features-thread-relationships-v1", _migration_6_parent_ending_features),
    (7, "closed-pattern-evidence-contract-v1", _migration_7_pattern_evidence_contract),
    (8, "browser-observations-url-identity-v1", _migration_8_browser_observations),
    (9, "browser-detail-attempt-failure-history-v1", _migration_9_browser_detail_attempts),
    (10, "browser-normalized-processing-bridge-v1", _migration_10_browser_normalized_bridge),
    (11, "m4-pattern-intelligence-provenance-v1", _migration_11_m4_pattern_intelligence),
    (12, "m4-sequence-pattern-members-v1", _migration_12_m4_sequence_patterns),
    (13, "browser-thread-sequence-observations-v1", _migration_13_browser_thread_sequences),
    (14, "structural-pattern-extraction-v1", _migration_14_structural_pattern_extraction),
    (15, "browser-text-quality-assessments-v1", _migration_15_browser_text_quality),
    (16, "durable-browser-detail-enrichment-queue-v1", _migration_16_detail_enrichment_queue),
    (17, "one-running-browser-detail-batch-v1", _migration_17_one_running_detail_batch),
    (18, "backfill-selected-browser-detail-queue-v1", _migration_18_backfill_selected_detail_queue),
    (
        19,
        "browser-metric-observation-statuses-v1",
        _migration_19_browser_metric_observation_statuses,
    ),
    (
        20,
        "browser-approximate-view-observations-v1",
        _migration_20_browser_approximate_view_observations,
    ),
    (
        21,
        "browser-detail-batch-assignment-history-v1",
        _migration_21_detail_batch_assignment_history,
    ),
    (
        22,
        "reconcile-browser-detail-batch-assignments-v1",
        _migration_22_reconcile_detail_batch_assignments,
    ),
    (
        23,
        "thread-sequence-relationship-evidence-v1",
        _migration_23_thread_sequence_relationship_evidence,
    ),
    (
        24,
        "browser-detail-enrichment-exclusions-v1",
        _migration_24_detail_enrichment_exclusions,
    ),
    (25, "browser-topic-tag-text-quality-v1", _migration_25_topic_tag_text_quality),
    (26, "browser-display-view-observations-v1", _migration_26_browser_display_view_observations),
)


class Repository:
    """Persist evidence and normalized derivatives through a small stable API."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.connection = sqlite3.connect(str(path))
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(SCHEMA)
        self._run_migrations()

    def _run_migrations(self) -> None:
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS schema_migrations (
              version INTEGER PRIMARY KEY,
              applied_at TEXT NOT NULL,
              migration_sha256 TEXT NOT NULL
            )"""
        )
        self.connection.commit()
        applied = {
            int(row["version"]): str(row["migration_sha256"])
            for row in self.connection.execute(
                "SELECT version, migration_sha256 FROM schema_migrations"
            ).fetchall()
        }
        for version, name, migration in MIGRATIONS:
            digest = hashlib.sha256((str(version) + ":" + name).encode("utf-8")).hexdigest()
            if version in applied:
                if applied[version] != digest:
                    raise RuntimeError("migration checksum mismatch for version " + str(version))
                continue
            try:
                self.connection.execute("BEGIN IMMEDIATE")
                migration(self.connection)
                self.connection.execute(
                    "INSERT INTO schema_migrations (version, applied_at, migration_sha256) "
                    "VALUES (?, ?, ?)",
                    (version, _utc_now(), digest),
                )
                self.connection.commit()
            except Exception:
                self.connection.rollback()
                raise

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "Repository":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def add_collection_run(
        self,
        *,
        endpoint: str,
        request: Dict[str, Any],
        started_at: str,
        completed_at: str,
        http_status: int,
        response_headers: Dict[str, str],
        raw_response: bytes,
        raw_response_sha256: str,
        collector_version: str,
    ) -> int:
        cursor = self.connection.execute(
            """INSERT INTO collection_runs
            (source, endpoint, request_json, started_at, completed_at, http_status,
             response_headers_json, raw_response, raw_response_sha256, collector_version)
            VALUES ('threads', ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                endpoint,
                json.dumps(request, ensure_ascii=False, sort_keys=True),
                started_at,
                completed_at,
                http_status,
                json.dumps(response_headers, ensure_ascii=False, sort_keys=True),
                raw_response,
                raw_response_sha256,
                collector_version,
            ),
        )
        self.connection.commit()
        if cursor.lastrowid is None:
            raise RuntimeError("SQLite did not return a collection run id")
        return int(cursor.lastrowid)

    def add_raw_post(
        self,
        *,
        collection_run_id: int,
        source_post_id: str,
        raw_json: bytes,
        raw_sha256: str,
        retrieved_at: str,
    ) -> int:
        cursor = self.connection.execute(
            """INSERT OR IGNORE INTO raw_posts
            (collection_run_id, source, source_post_id, raw_json, raw_sha256, retrieved_at)
            VALUES (?, 'threads', ?, ?, ?, ?)""",
            (collection_run_id, source_post_id, raw_json, raw_sha256, retrieved_at),
        )
        self.connection.commit()
        if cursor.rowcount:
            if cursor.lastrowid is None:
                raise RuntimeError("SQLite did not return a raw post id")
            return int(cursor.lastrowid)
        row = self.connection.execute(
            """SELECT id FROM raw_posts
            WHERE collection_run_id = ? AND source = 'threads'
              AND source_post_id = ? AND raw_sha256 = ?""",
            (collection_run_id, source_post_id, raw_sha256),
        ).fetchone()
        if row is None:
            raise RuntimeError("SQLite did not return the existing raw post id")
        return int(row["id"])

    def upsert_normalized_post(
        self,
        post: Dict[str, Any],
        *,
        source_raw_post_id: Optional[int] = None,
        normalizer_version: str = "m0-normalizer-v1",
    ) -> None:
        columns = (
            "source",
            "source_post_id",
            "author_id",
            "username",
            "text",
            "permalink",
            "published_at",
            "media_type",
            "raw_sha256",
            "normalized_at",
        )
        values = tuple(post[name] for name in columns)
        canonical = _canonical_normalized_payload(post)
        payload_json = _canonical_json(canonical)
        payload_sha256 = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
        with self.connection:
            self.connection.execute(
                """INSERT INTO normalized_posts
                (source, source_post_id, author_id, username, text, permalink, published_at,
                 media_type, raw_sha256, normalized_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source, source_post_id) DO NOTHING""",
                values,
            )
            identity = self.connection.execute(
                "SELECT id FROM normalized_posts WHERE source = ? AND source_post_id = ?",
                (post["source"], post["source_post_id"]),
            ).fetchone()
            if identity is None:
                raise RuntimeError("normalized post identity was not created")
            normalized_post_id = int(identity["id"])
            version_row = self.connection.execute(
                """SELECT id FROM normalized_post_versions
                WHERE normalized_post_id = ? AND payload_sha256 = ?""",
                (normalized_post_id, payload_sha256),
            ).fetchone()
            if version_row is None:
                next_version = int(
                    self.connection.execute(
                        """SELECT COALESCE(MAX(version), 0) + 1
                        FROM normalized_post_versions WHERE normalized_post_id = ?""",
                        (normalized_post_id,),
                    ).fetchone()[0]
                )
                cursor = self.connection.execute(
                    """INSERT INTO normalized_post_versions
                    (normalized_post_id, version, canonical_payload_json, payload_sha256,
                     source_raw_post_id, normalized_at, normalizer_version)
                    VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        normalized_post_id,
                        next_version,
                        payload_json,
                        payload_sha256,
                        source_raw_post_id,
                        post["normalized_at"],
                        normalizer_version,
                    ),
                )
                if cursor.lastrowid is None:
                    raise RuntimeError("SQLite did not return a normalized post version id")
                version_id = int(cursor.lastrowid)
            else:
                version_id = int(version_row["id"])
            self.connection.execute(
                """UPDATE normalized_posts SET
                  author_id=?, username=?, text=?, permalink=?, published_at=?, media_type=?,
                  raw_sha256=?, normalized_at=?, current_version_id=?
                WHERE id=?""",
                values[2:] + (version_id, normalized_post_id),
            )

    def create_collection_batch(
        self,
        batch_key: str,
        config: Dict[str, Any],
        collector_version: str,
        *,
        started_at: Optional[str] = None,
    ) -> int:
        config_json = _canonical_json(config)
        cursor = self.connection.execute(
            """INSERT INTO collection_batches
            (batch_key, status, config_json, config_sha256, started_at, collector_version)
            VALUES (?, 'RUNNING', ?, ?, ?, ?)""",
            (
                batch_key,
                config_json,
                hashlib.sha256(config_json.encode("utf-8")).hexdigest(),
                started_at or _utc_now(),
                collector_version,
            ),
        )
        self.connection.commit()
        if cursor.lastrowid is None:
            raise RuntimeError("SQLite did not return a collection batch id")
        return int(cursor.lastrowid)

    def complete_collection_batch(
        self, batch_id: int, *, completed_at: Optional[str] = None, failed: bool = False
    ) -> None:
        cursor = self.connection.execute(
            """UPDATE collection_batches SET status = ?, completed_at = ?
            WHERE id = ? AND status = 'RUNNING'""",
            ("FAILED" if failed else "COMPLETE", completed_at or _utc_now(), batch_id),
        )
        self.connection.commit()
        if cursor.rowcount != 1:
            raise ValueError("collection batch is not RUNNING")

    def add_collection_batch_query(self, batch_id: int, ordinal: int, query: Dict[str, Any]) -> int:
        batch = self.connection.execute(
            "SELECT status FROM collection_batches WHERE id = ?", (batch_id,)
        ).fetchone()
        if batch is None or batch["status"] != "RUNNING":
            raise ValueError("collection batch is not RUNNING")
        query_json = _canonical_json(query)
        cursor = self.connection.execute(
            """INSERT INTO collection_batch_queries
            (collection_batch_id, ordinal, query_json, query_sha256)
            VALUES (?, ?, ?, ?)""",
            (
                batch_id,
                ordinal,
                query_json,
                hashlib.sha256(query_json.encode("utf-8")).hexdigest(),
            ),
        )
        self.connection.commit()
        if cursor.lastrowid is None:
            raise RuntimeError("SQLite did not return a collection batch query id")
        return int(cursor.lastrowid)

    def link_collection_run(self, batch_query_id: int, collection_run_id: int) -> int:
        query = self.connection.execute(
            """SELECT collection_batches.status
            FROM collection_batch_queries
            JOIN collection_batches
              ON collection_batches.id = collection_batch_queries.collection_batch_id
            WHERE collection_batch_queries.id = ?""",
            (batch_query_id,),
        ).fetchone()
        if query is None or query["status"] != "RUNNING":
            raise ValueError("collection batch is not RUNNING")
        cursor = self.connection.execute(
            """INSERT INTO collection_batch_runs
            (collection_batch_query_id, collection_run_id) VALUES (?, ?)""",
            (batch_query_id, collection_run_id),
        )
        self.connection.commit()
        if cursor.lastrowid is None:
            raise RuntimeError("SQLite did not return a collection batch run id")
        return int(cursor.lastrowid)

    def create_dataset_snapshot(
        self,
        dataset_key: str,
        version: int,
        selection_spec: Dict[str, Any],
        *,
        created_at: Optional[str] = None,
    ) -> int:
        selection_json = _canonical_json(selection_spec)
        cursor = self.connection.execute(
            """INSERT INTO dataset_snapshots
            (dataset_key, version, status, selection_spec_json, selection_spec_sha256,
             created_at)
            VALUES (?, ?, 'DRAFT', ?, ?, ?)""",
            (
                dataset_key,
                version,
                selection_json,
                hashlib.sha256(selection_json.encode("utf-8")).hexdigest(),
                created_at or _utc_now(),
            ),
        )
        self.connection.commit()
        if cursor.lastrowid is None:
            raise RuntimeError("SQLite did not return a dataset snapshot id")
        return int(cursor.lastrowid)

    def add_dataset_member(
        self,
        snapshot_id: int,
        normalized_post_version_id: int,
        selected_raw_post_id: int,
        ordinal: int,
        inclusion_reason: Dict[str, Any],
    ) -> int:
        valid = self.connection.execute(
            """SELECT dataset_snapshots.status
            FROM dataset_snapshots, normalized_post_versions
            JOIN normalized_posts
              ON normalized_posts.id = normalized_post_versions.normalized_post_id
            JOIN raw_posts
              ON raw_posts.id = ?
             AND raw_posts.source = normalized_posts.source
             AND raw_posts.source_post_id = normalized_posts.source_post_id
            WHERE dataset_snapshots.id = ? AND normalized_post_versions.id = ?""",
            (selected_raw_post_id, snapshot_id, normalized_post_version_id),
        ).fetchone()
        if valid is None:
            raise ValueError("dataset member provenance is inconsistent")
        if valid["status"] != "DRAFT":
            raise ValueError("finalized dataset snapshot is immutable")
        reason_json = _canonical_json(inclusion_reason)
        cursor = self.connection.execute(
            """INSERT INTO dataset_members
            (dataset_snapshot_id, normalized_post_version_id, selected_raw_post_id,
             ordinal, inclusion_reason_json)
            VALUES (?, ?, ?, ?, ?)""",
            (
                snapshot_id,
                normalized_post_version_id,
                selected_raw_post_id,
                ordinal,
                reason_json,
            ),
        )
        self.connection.commit()
        if cursor.lastrowid is None:
            raise RuntimeError("SQLite did not return a dataset member id")
        return int(cursor.lastrowid)

    def finalize_dataset_snapshot(
        self, snapshot_id: int, *, finalized_at: Optional[str] = None
    ) -> None:
        cursor = self.connection.execute(
            """UPDATE dataset_snapshots SET status = 'FINALIZED', finalized_at = ?
            WHERE id = ? AND status = 'DRAFT'""",
            (finalized_at or _utc_now(), snapshot_id),
        )
        self.connection.commit()
        if cursor.rowcount != 1:
            raise ValueError("dataset snapshot is not mutable")

    def assess_browser_text_quality(
        self,
        *,
        browser_observation_id: int,
        quality_status: str,
        input_sha256: str,
        assessor_version: str = ASSESSOR_VERSION,
        assessed_at: Optional[str] = None,
    ) -> int:
        """Append the quality state of one source observation; never alter the source."""
        if quality_status not in {
            VALID_TEXT,
            INVALID_TEXT_DATE_METADATA,
            INVALID_TEXT_TOPIC_TAG_METADATA,
            TEXT_UNAVAILABLE,
        }:
            raise ValueError("unsupported browser text quality status")
        if not _is_contract_identifier(assessor_version):
            raise ValueError("browser text assessor version is invalid")
        if not isinstance(input_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", input_sha256):
            raise ValueError("browser text quality input hash is invalid")
        observation = self.connection.execute(
            "SELECT id FROM browser_observations WHERE id = ?", (browser_observation_id,)
        ).fetchone()
        if observation is None:
            raise KeyError("browser observation not found")
        cursor = self.connection.execute(
            """INSERT INTO browser_text_quality_assessments
            (browser_observation_id, quality_status, assessor_version, input_sha256, assessed_at)
            VALUES (?, ?, ?, ?, ?)""",
            (
                browser_observation_id,
                quality_status,
                assessor_version,
                input_sha256,
                assessed_at or _utc_now(),
            ),
        )
        self.connection.commit()
        if cursor.lastrowid is None:
            raise RuntimeError("SQLite did not return a browser text quality assessment id")
        return int(cursor.lastrowid)

    def add_metric_observation(
        self,
        *,
        source: str,
        source_post_id: str,
        metric_name: str,
        metric_value: int,
        observed_at: str,
        api_field: str,
        unit: str,
        collector_version: str,
        raw_post_id: Optional[int] = None,
        collection_run_id: Optional[int] = None,
    ) -> int:
        if isinstance(metric_value, bool) or not isinstance(metric_value, int):
            raise TypeError("metric_value must be an integer")
        if metric_value < 0:
            raise ValueError("metric_value must be nonnegative")
        if raw_post_id is None and collection_run_id is None:
            raise ValueError("metric observation requires raw or collection-run provenance")
        if raw_post_id is not None:
            raw = self.connection.execute(
                """SELECT collection_run_id FROM raw_posts
                WHERE id = ? AND source = ? AND source_post_id = ?""",
                (raw_post_id, source, source_post_id),
            ).fetchone()
            if raw is None:
                raise ValueError("raw metric provenance does not match the source post")
            if collection_run_id is not None and int(raw["collection_run_id"]) != collection_run_id:
                raise ValueError("raw and collection-run metric provenance disagree")
        cursor = self.connection.execute(
            """INSERT INTO post_metric_observations
            (source, source_post_id, metric_name, metric_value, observed_at, raw_post_id,
             collection_run_id, api_field, unit, collector_version)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                source,
                source_post_id,
                metric_name,
                metric_value,
                observed_at,
                raw_post_id,
                collection_run_id,
                api_field,
                unit,
                collector_version,
            ),
        )
        self.connection.commit()
        if cursor.lastrowid is None:
            raise RuntimeError("SQLite did not return a metric observation id")
        return int(cursor.lastrowid)

    def add_browser_observation(
        self,
        observation: Dict[str, Any],
        *,
        detail_attempt: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Append one closed browser observation and version its normalized projection."""
        canonical_url = validate_browser_observation(observation)
        if detail_attempt is not None:
            if observation["observation_type"] != "POST_DETAIL":
                raise ValueError("detail attempt requires a POST_DETAIL observation")
            if set(detail_attempt) != {
                "attempted_at",
                "extractor_version",
                "contract_version",
            }:
                raise ValueError("detail attempt does not match the closed contract")
            validate_detail_attempt_provenance(**detail_attempt)
        status = browser_observation_status(observation)
        source_post_id = observation.get("source_post_id")
        canonical_observation_json = _canonical_json(observation)
        fields = observation["observed_fields"]
        field_provenance_json = json.dumps(
            fields, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True
        )
        field_provenance_sha256 = hashlib.sha256(field_provenance_json.encode("utf-8")).hexdigest()
        normalized = browser_normalized_payload(observation)
        normalized_json = canonical_browser_normalized_payload(observation)
        normalized_sha256 = hashlib.sha256(normalized_json.encode("utf-8")).hexdigest()
        with self.connection:
            identity = self.connection.execute(
                "SELECT * FROM browser_post_identities WHERE post_url = ?", (canonical_url,)
            ).fetchone()
            if identity is None:
                cursor = self.connection.execute(
                    """INSERT INTO browser_post_identities
                    (source, post_url, source_post_id, status, created_at, updated_at)
                    VALUES ('threads', ?, ?, ?, ?, ?)""",
                    (
                        canonical_url,
                        source_post_id,
                        status,
                        observation["collected_at"],
                        observation["collected_at"],
                    ),
                )
                if cursor.lastrowid is None:
                    raise RuntimeError("SQLite did not return a browser post identity id")
                identity_id = int(cursor.lastrowid)
            else:
                identity_id = int(identity["id"])
                existing_source_post_id = identity["source_post_id"]
                if (
                    source_post_id is not None
                    and existing_source_post_id is not None
                    and source_post_id != existing_source_post_id
                ):
                    raise ValueError("browser observation source post id conflicts with identity")
            identity_status = status
            if identity is not None and identity["status"] == "DETAIL_ENRICHED":
                identity_status = "DETAIL_ENRICHED"
            elif (
                identity is not None
                and identity["status"] == "DETAIL_FAILED"
                and observation["observation_type"] == "SEARCH_CARD"
            ):
                identity_status = "DETAIL_FAILED"
            cursor = self.connection.execute(
                """INSERT INTO browser_observations
                (browser_post_identity_id, observation_type, source, post_url, source_post_id,
                 status, canonical_payload_json, payload_sha256, field_provenance_json,
                 field_provenance_sha256, collection_context_json, collected_at,
                 extractor_version)
                VALUES (?, ?, 'threads', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    identity_id,
                    observation["observation_type"],
                    canonical_url,
                    source_post_id,
                    status,
                    canonical_observation_json,
                    observation["payload_sha256"],
                    field_provenance_json,
                    field_provenance_sha256,
                    _canonical_json(observation["collection_context"]),
                    observation["collected_at"],
                    observation["extractor_version"],
                ),
            )
            if cursor.lastrowid is None:
                raise RuntimeError("SQLite did not return a browser observation id")
            observation_id = int(cursor.lastrowid)
            if observation["observation_type"] == "POST_DETAIL":
                new_text = observation.get("text")
                topic_tags = observation.get("topic_tags", [])
                if isinstance(topic_tags, list):
                    for previous in self.connection.execute(
                        """SELECT old.id, old.canonical_payload_json
                        FROM browser_observations old
                        WHERE old.browser_post_identity_id = ? AND old.id != ?
                          AND old.observation_type = 'POST_DETAIL'
                          AND COALESCE((SELECT quality_status
                               FROM browser_text_quality_assessments quality
                               WHERE quality.browser_observation_id = old.id
                               ORDER BY quality.id DESC LIMIT 1), 'VALID_TEXT') = 'VALID_TEXT'""",
                        (identity_id, observation_id),
                    ).fetchall():
                        previous_payload = json.loads(previous["canonical_payload_json"])
                        previous_text = previous_payload.get("text")
                        if (
                            isinstance(previous_text, str)
                            and previous_text in topic_tags
                            and previous_text != new_text
                        ):
                            self.connection.execute(
                                """INSERT INTO browser_text_quality_assessments
                                (browser_observation_id, quality_status, assessor_version,
                                 input_sha256, assessed_at)
                                VALUES (?, 'INVALID_TEXT_TOPIC_TAG_METADATA', ?, ?, ?)""",
                                (
                                    int(previous["id"]),
                                    "m4-browser-topic-tag-quality-v1",
                                    hashlib.sha256(previous_text.encode("utf-8")).hexdigest(),
                                    observation["collected_at"],
                                ),
                            )
            for field in fields:
                self.connection.execute(
                    """INSERT INTO browser_observed_fields
                    (browser_observation_id, field_name, observed_value_json, surface,
                     observed_at, extractor_version)
                    VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        observation_id,
                        field["field"],
                        json.dumps(
                            field["value"],
                            ensure_ascii=False,
                            allow_nan=False,
                            separators=(",", ":"),
                            sort_keys=True,
                        ),
                        field["surface"],
                        field["observed_at"],
                        field["extractor_version"],
                    ),
                )
            metric_statuses = observation.get("metric_observation_statuses")
            if metric_statuses is not None:
                for metric_name, metric_status in metric_statuses.items():
                    self.connection.execute(
                        """INSERT INTO browser_metric_observation_statuses
                        (browser_observation_id, field_name, observation_status, surface,
                         observed_at, extractor_version)
                        VALUES (?, ?, ?, 'threads_post_detail', ?, ?)""",
                        (
                            observation_id,
                            "public_counters." + metric_name,
                            metric_status,
                            observation["collected_at"],
                            observation["extractor_version"],
                        ),
                    )
            approximate_views = observation.get("approximate_views")
            if approximate_views is not None:
                self.connection.execute(
                    """INSERT INTO browser_approximate_view_observations
                    (browser_observation_id, display, normalized_approx, precision,
                     source, view_band, observed_at, extractor_version,
                     normalizer_version)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        observation_id,
                        approximate_views["display"],
                        approximate_views["normalized_approx"],
                        approximate_views["precision"],
                        approximate_views["source"],
                        approximate_views["view_band"],
                        approximate_views["observed_at"],
                        approximate_views["extractor_version"],
                        approximate_views["normalizer_version"],
                    ),
                )
            display_views = observation.get("display_views")
            if display_views is not None:
                self.connection.execute(
                    """INSERT INTO browser_display_view_observations
                    (browser_observation_id, display, normalized_value, precision,
                     source, view_band, observed_at, extractor_version,
                     normalizer_version)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        observation_id,
                        display_views["display"],
                        display_views["normalized_value"],
                        display_views["precision"],
                        display_views["source"],
                        display_views["view_band"],
                        display_views["observed_at"],
                        display_views["extractor_version"],
                        display_views["normalizer_version"],
                    ),
                )
            version = self.connection.execute(
                """SELECT id, version FROM browser_normalized_versions
                WHERE browser_post_identity_id = ? AND payload_sha256 = ?""",
                (identity_id, normalized_sha256),
            ).fetchone()
            reused = version is not None
            if version is None:
                next_version = int(
                    self.connection.execute(
                        """SELECT COALESCE(MAX(version), 0) + 1
                        FROM browser_normalized_versions WHERE browser_post_identity_id = ?""",
                        (identity_id,),
                    ).fetchone()[0]
                )
                cursor = self.connection.execute(
                    """INSERT INTO browser_normalized_versions
                    (browser_post_identity_id, version, canonical_payload_json,
                     payload_sha256, source_observation_id, normalized_at, normalizer_version)
                    VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        identity_id,
                        next_version,
                        normalized_json,
                        normalized_sha256,
                        observation_id,
                        observation["collected_at"],
                        BROWSER_NORMALIZER_VERSION,
                    ),
                )
                if cursor.lastrowid is None:
                    raise RuntimeError("SQLite did not return a browser normalized version id")
                version_id = int(cursor.lastrowid)
                version_number = next_version
            else:
                version_id = int(version["id"])
                version_number = int(version["version"])
            self.connection.execute(
                """UPDATE browser_post_identities SET
                  source_post_id = COALESCE(source_post_id, ?), status = ?,
                  current_observation_id = ?, current_normalized_version_id = ?, updated_at = ?
                WHERE id = ?""",
                (
                    normalized["source_post_id"],
                    identity_status,
                    observation_id,
                    version_id,
                    observation["collected_at"],
                    identity_id,
                ),
            )
            detail_attempt_id: Optional[int] = None
            if detail_attempt is not None:
                attempt_cursor = self.connection.execute(
                    """INSERT INTO browser_detail_attempts
                    (browser_post_identity_id, post_url, attempted_at, extractor_version,
                     contract_version, outcome, detail_observation_id)
                    VALUES (?, ?, ?, ?, ?, 'SUCCEEDED', ?)""",
                    (
                        identity_id,
                        canonical_url,
                        detail_attempt["attempted_at"],
                        detail_attempt["extractor_version"],
                        detail_attempt["contract_version"],
                        observation_id,
                    ),
                )
                if attempt_cursor.lastrowid is None:
                    raise RuntimeError("SQLite did not return a browser detail attempt id")
                detail_attempt_id = int(attempt_cursor.lastrowid)
            if observation["observation_type"] == "SEARCH_CARD" and status == "DETAIL_PENDING":
                # The first accepted pending capture is the durable queue provenance.
                # Duplicate captures append observation history without replacing it.
                self.connection.execute(
                    """INSERT INTO browser_detail_enrichment_queue
                    (browser_post_identity_id, source_observation_id, status,
                     enqueued_at, updated_at)
                    VALUES (?, ?, 'DETAIL_PENDING', ?, ?)
                    ON CONFLICT(browser_post_identity_id) DO NOTHING""",
                    (
                        identity_id,
                        observation_id,
                        observation["collected_at"],
                        observation["collected_at"],
                    ),
                )
        return {
            "browser_post_identity_id": identity_id,
            "browser_observation_id": observation_id,
            "browser_normalized_version_id": version_id,
            "browser_normalized_version": version_number,
            "normalized_version_reused": reused,
            "status": status,
            "post_url": canonical_url,
            "browser_detail_attempt_id": detail_attempt_id,
        }

    def bridge_browser_post(self, post_url: str) -> Dict[str, Any]:
        """Explicitly project the accepted current browser version into M1/M2 identity."""
        canonical_url = canonical_threads_post_url(post_url)
        row = self.connection.execute(
            """SELECT browser_post_identities.id AS identity_id,
                      browser_post_identities.current_normalized_version_id,
                      browser_normalized_versions.canonical_payload_json,
                      browser_normalized_versions.source_observation_id,
                      browser_normalized_versions.normalized_at
            FROM browser_post_identities
            JOIN browser_normalized_versions
              ON browser_normalized_versions.id =
                 browser_post_identities.current_normalized_version_id
            WHERE browser_post_identities.post_url = ?""",
            (canonical_url,),
        ).fetchone()
        if row is None:
            raise KeyError("accepted browser post not found: " + canonical_url)
        browser_payload = json.loads(str(row["canonical_payload_json"]))
        if not isinstance(browser_payload, dict):
            raise RuntimeError("browser normalized payload is not an object")
        post = {
            "schema_version": 1,
            "source": "threads_browser",
            "source_post_id": canonical_url,
            "author_id": None,
            "username": browser_payload.get("username"),
            "text": browser_payload.get("text"),
            "permalink": canonical_url,
            "published_at": browser_payload.get("timestamp"),
            "media_type": browser_payload.get("media_type"),
            "raw_sha256": hashlib.sha256(
                str(row["canonical_payload_json"]).encode("utf-8")
            ).hexdigest(),
            "normalized_at": str(row["normalized_at"]),
        }
        self.upsert_normalized_post(post, normalizer_version="m3-browser-bridge-v1")
        normalized = self.connection.execute(
            """SELECT normalized_posts.id AS post_id,
                      normalized_posts.current_version_id AS version_id,
                      normalized_post_versions.version
            FROM normalized_posts
            JOIN normalized_post_versions
              ON normalized_post_versions.id = normalized_posts.current_version_id
            WHERE normalized_posts.source = 'threads_browser'
              AND normalized_posts.source_post_id = ?""",
            (canonical_url,),
        ).fetchone()
        if normalized is None:
            raise RuntimeError("browser bridge normalized identity was not created")
        with self.connection:
            self.connection.execute(
                """INSERT INTO browser_normalized_bridges
                (browser_post_identity_id, browser_normalized_version_id,
                 normalized_post_id, normalized_post_version_id, bridged_at, bridge_version)
                VALUES (?, ?, ?, ?, ?, 'm3-browser-bridge-v1')
                ON CONFLICT(browser_normalized_version_id) DO NOTHING""",
                (
                    int(row["identity_id"]),
                    int(row["current_normalized_version_id"]),
                    int(normalized["post_id"]),
                    int(normalized["version_id"]),
                    _utc_now(),
                ),
            )
            bridge = self.connection.execute(
                """SELECT * FROM browser_normalized_bridges
                WHERE browser_normalized_version_id = ?""",
                (int(row["current_normalized_version_id"]),),
            ).fetchone()
            if bridge is None or int(bridge["normalized_post_version_id"]) != int(
                normalized["version_id"]
            ):
                raise ValueError("browser bridge replay does not match normalized evidence")
        return {
            "source": "threads_browser",
            "source_post_id": canonical_url,
            "browser_post_identity_id": int(row["identity_id"]),
            "browser_normalized_version_id": int(row["current_normalized_version_id"]),
            "source_browser_observation_id": int(row["source_observation_id"]),
            "normalized_post_id": int(normalized["post_id"]),
            "normalized_post_version_id": int(normalized["version_id"]),
            "normalized_post_version": int(normalized["version"]),
        }

    def bridge_unbridged_browser_posts(self, *, limit: int = 100) -> int:
        """Explicit local-only bridge for accepted browser identities awaiting projection."""
        if not isinstance(limit, int) or limit < 1 or limit > 100:
            raise ValueError("bridge limit must be between 1 and 100")
        rows = self.connection.execute(
            """SELECT browser_post_identities.post_url
            FROM browser_post_identities
            LEFT JOIN browser_normalized_bridges
              ON browser_normalized_bridges.browser_normalized_version_id =
                 browser_post_identities.current_normalized_version_id
            WHERE browser_post_identities.current_normalized_version_id IS NOT NULL
              AND browser_normalized_bridges.id IS NULL
            ORDER BY browser_post_identities.id LIMIT ?""",
            (limit,),
        ).fetchall()
        for row in rows:
            self.bridge_browser_post(str(row["post_url"]))
        return len(rows)

    def record_browser_thread_sequence_observation(
        self,
        *,
        root_identity_id: int,
        node_identity_id: int,
        reply_to_identity_id: Optional[int],
        sequence_position: int,
        same_author_as_root: Optional[bool],
        detail_observation_id: int,
        extractor_version: str,
        observed_at: Optional[str] = None,
        relationship_evidence: Optional[str] = None,
    ) -> int:
        """Append one visible thread node without inferring an edge or author match."""
        return self.record_browser_thread_sequence_observations(
            root_identity_id=root_identity_id,
            detail_observation_id=detail_observation_id,
            extractor_version=extractor_version,
            entries=[
                {
                    "node_identity_id": node_identity_id,
                    "reply_to_identity_id": reply_to_identity_id,
                    "sequence_position": sequence_position,
                    "same_author_as_root": same_author_as_root,
                    "relationship_evidence": relationship_evidence,
                    "observed_at": observed_at,
                }
            ],
        )[0]

    def record_browser_thread_sequence_observations(
        self,
        *,
        root_identity_id: int,
        detail_observation_id: int,
        extractor_version: str,
        entries: Sequence[Mapping[str, Any]],
    ) -> Tuple[int, ...]:
        """Atomically append visible nodes tied to one root detail observation."""
        if not entries or not _is_contract_identifier(extractor_version):
            raise ValueError("invalid browser thread sequence observation")
        detail = self.connection.execute(
            """SELECT id FROM browser_observations
            WHERE id = ? AND browser_post_identity_id = ? AND observation_type = 'POST_DETAIL'""",
            (detail_observation_id, root_identity_id),
        ).fetchone()
        if detail is None:
            raise ValueError("thread sequence requires matching detail observation")
        inserted: List[int] = []
        with self.connection:
            for entry in entries:
                node_identity_id = entry.get("node_identity_id")
                reply_to_identity_id = entry.get("reply_to_identity_id")
                sequence_position = entry.get("sequence_position")
                same_author_as_root = entry.get("same_author_as_root")
                relationship_evidence = entry.get("relationship_evidence")
                observed_at = entry.get("observed_at") or _utc_now()
                if (
                    not isinstance(node_identity_id, int)
                    or (
                        reply_to_identity_id is not None
                        and not isinstance(reply_to_identity_id, int)
                    )
                    or not isinstance(sequence_position, int)
                    or sequence_position < 0
                    or same_author_as_root not in {None, True, False}
                    or relationship_evidence
                    not in {None, "ROOT_DETAIL_PAGE", "DOM_CONTIGUOUS_ROOT_AUTHOR_CHAIN"}
                    or not isinstance(observed_at, str)
                ):
                    raise ValueError("invalid browser thread sequence observation")
                cursor = self.connection.execute(
                    """INSERT INTO browser_thread_sequence_observations
                    (root_browser_post_identity_id, node_browser_post_identity_id,
                     reply_to_browser_post_identity_id, sequence_position, same_author_as_root,
                     detail_observation_id, observed_at, extractor_version,
                     relationship_evidence)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        root_identity_id,
                        node_identity_id,
                        reply_to_identity_id,
                        sequence_position,
                        None if same_author_as_root is None else int(same_author_as_root),
                        detail_observation_id,
                        observed_at,
                        extractor_version,
                        relationship_evidence,
                    ),
                )
                if cursor.lastrowid is None:
                    raise RuntimeError("SQLite did not return a thread sequence observation id")
                inserted.append(int(cursor.lastrowid))
        return tuple(inserted)

    def add_browser_dataset_member(
        self,
        snapshot_id: int,
        normalized_post_version_id: int,
        selected_browser_observation_id: int,
        ordinal: int,
        inclusion_reason: Dict[str, Any],
    ) -> int:
        valid = self.connection.execute(
            """SELECT dataset_snapshots.status
            FROM dataset_snapshots
            JOIN browser_normalized_bridges
              ON browser_normalized_bridges.normalized_post_version_id = ?
            JOIN browser_normalized_versions
              ON browser_normalized_versions.id =
                 browser_normalized_bridges.browser_normalized_version_id
             AND browser_normalized_versions.source_observation_id = ?
            WHERE dataset_snapshots.id = ?""",
            (normalized_post_version_id, selected_browser_observation_id, snapshot_id),
        ).fetchone()
        if valid is None:
            raise ValueError("browser dataset member provenance is inconsistent")
        if valid["status"] != "DRAFT":
            raise ValueError("finalized dataset snapshot is immutable")
        cursor = self.connection.execute(
            """INSERT INTO dataset_members
            (dataset_snapshot_id, normalized_post_version_id, selected_raw_post_id,
             selected_browser_observation_id, ordinal, inclusion_reason_json)
            VALUES (?, ?, NULL, ?, ?, ?)""",
            (
                snapshot_id,
                normalized_post_version_id,
                selected_browser_observation_id,
                ordinal,
                _canonical_json(inclusion_reason),
            ),
        )
        self.connection.commit()
        if cursor.lastrowid is None:
            raise RuntimeError("SQLite did not return a browser dataset member id")
        return int(cursor.lastrowid)

    def record_browser_detail_success(
        self,
        *,
        browser_observation_id: int,
        attempted_at: str,
        extractor_version: str,
        contract_version: str = DETAIL_ATTEMPT_CONTRACT_VERSION,
    ) -> int:
        """Append attempt provenance for an accepted POST_DETAIL observation."""
        validate_detail_attempt_provenance(
            attempted_at=attempted_at,
            extractor_version=extractor_version,
            contract_version=contract_version,
        )
        observation = self.connection.execute(
            """SELECT browser_observations.*, browser_post_identities.status AS identity_status
            FROM browser_observations
            JOIN browser_post_identities
              ON browser_post_identities.id = browser_observations.browser_post_identity_id
            WHERE browser_observations.id = ?""",
            (browser_observation_id,),
        ).fetchone()
        if observation is None:
            raise KeyError("browser observation not found: " + str(browser_observation_id))
        if observation["observation_type"] != "POST_DETAIL":
            raise ValueError("detail success must reference a POST_DETAIL observation")
        with self.connection:
            cursor = self.connection.execute(
                """INSERT INTO browser_detail_attempts
                (browser_post_identity_id, post_url, attempted_at, extractor_version,
                 contract_version, outcome, detail_observation_id)
                VALUES (?, ?, ?, ?, ?, 'SUCCEEDED', ?)""",
                (
                    observation["browser_post_identity_id"],
                    observation["post_url"],
                    attempted_at,
                    extractor_version,
                    contract_version,
                    browser_observation_id,
                ),
            )
        if cursor.lastrowid is None:
            raise RuntimeError("SQLite did not return a browser detail attempt id")
        return int(cursor.lastrowid)

    def record_browser_detail_failure(
        self,
        *,
        post_url: str,
        attempted_at: str,
        extractor_version: str,
        failure_type: str,
        failure_reason: str,
        contract_version: str = DETAIL_ATTEMPT_CONTRACT_VERSION,
    ) -> int:
        """Append a bounded failure without storing DOM, credentials, or free-form detail."""
        canonical_url = canonical_threads_post_url(post_url)
        if canonical_url != post_url:
            raise ValueError("post_url must already be canonical")
        validate_detail_attempt_provenance(
            attempted_at=attempted_at,
            extractor_version=extractor_version,
            contract_version=contract_version,
        )
        validate_detail_failure(failure_type, failure_reason)
        identity = self.connection.execute(
            "SELECT id, status FROM browser_post_identities WHERE post_url = ?",
            (canonical_url,),
        ).fetchone()
        if identity is None:
            raise KeyError("browser post identity not found: " + canonical_url)
        with self.connection:
            cursor = self.connection.execute(
                """INSERT INTO browser_detail_attempts
                (browser_post_identity_id, post_url, attempted_at, extractor_version,
                 contract_version, outcome, detail_observation_id)
                VALUES (?, ?, ?, ?, ?, 'FAILED', NULL)""",
                (
                    identity["id"],
                    canonical_url,
                    attempted_at,
                    extractor_version,
                    contract_version,
                ),
            )
            if cursor.lastrowid is None:
                raise RuntimeError("SQLite did not return a browser detail attempt id")
            attempt_id = int(cursor.lastrowid)
            self.connection.execute(
                """INSERT INTO browser_detail_failures
                (browser_detail_attempt_id, failure_type, failure_reason)
                VALUES (?, ?, ?)""",
                (attempt_id, failure_type, failure_reason),
            )
            if identity["status"] != "DETAIL_ENRICHED":
                self.connection.execute(
                    """UPDATE browser_post_identities
                    SET status = 'DETAIL_FAILED', updated_at = ? WHERE id = ?""",
                    (attempted_at, identity["id"]),
                )
        return attempt_id

    def start_browser_detail_batch(
        self,
        *,
        requested_items: int,
        max_items: int,
        started_at: Optional[str] = None,
    ) -> int:
        if isinstance(requested_items, bool) or not isinstance(requested_items, int):
            raise TypeError("requested_items must be an integer")
        if isinstance(max_items, bool) or not isinstance(max_items, int):
            raise TypeError("max_items must be an integer")
        if requested_items < 1 or max_items < 1 or requested_items > max_items:
            raise ValueError("detail batch item bounds are invalid")
        running = self.connection.execute(
            """SELECT id FROM browser_detail_enrichment_batches
            WHERE status = 'RUNNING' ORDER BY id LIMIT 1"""
        ).fetchone()
        if running is not None:
            return int(running["id"])
        cursor = self.connection.execute(
            """INSERT INTO browser_detail_enrichment_batches
            (status, requested_items, max_items, started_at)
            VALUES ('RUNNING', ?, ?, ?)""",
            (requested_items, max_items, started_at or _utc_now()),
        )
        self.connection.commit()
        if cursor.lastrowid is None:
            raise RuntimeError("SQLite did not return a detail batch id")
        return int(cursor.lastrowid)

    def resume_browser_detail_batch(self, batch_id: int) -> Dict[str, Any]:
        with self.connection:
            row = self.connection.execute(
                "SELECT * FROM browser_detail_enrichment_batches WHERE id = ?", (batch_id,)
            ).fetchone()
            if row is None:
                raise KeyError("detail batch not found: " + str(batch_id))
            if row["status"] != "RUNNING":
                raise ValueError("detail batch is not RUNNING")
            # A browser/service-worker restart loses the in-memory claimant. Release only
            # this batch's leases and advance their version so replayed old responses fail.
            self.connection.execute(
                """UPDATE browser_detail_enrichment_queue SET
                status = 'DETAIL_PENDING', claimed_at = NULL,
                lease_version = lease_version + 1,
                last_error_code = NULL, last_error_type = NULL, last_error_reason = NULL,
                updated_at = ?
                WHERE active_batch_id = ? AND status = 'DETAIL_PROCESSING'""",
                (_utc_now(), batch_id),
            )
        return self.browser_detail_batch_summary(batch_id)

    def browser_detail_batch_summary(self, batch_id: int) -> Dict[str, Any]:
        batch = self.connection.execute(
            "SELECT * FROM browser_detail_enrichment_batches WHERE id = ?", (batch_id,)
        ).fetchone()
        if batch is None:
            raise KeyError("detail batch not found: " + str(batch_id))
        counts = {
            str(row["status"]): int(row["count"])
            for row in self.connection.execute(
                """SELECT status, COUNT(*) AS count FROM browser_detail_enrichment_queue
                WHERE active_batch_id = ? GROUP BY status""",
                (batch_id,),
            ).fetchall()
        }
        result = dict(batch)
        result["counts"] = counts
        result["assigned_items"] = sum(counts.values())
        return result

    def finish_browser_detail_batch(
        self, batch_id: int, *, stopped: bool = False, completed_at: Optional[str] = None
    ) -> Dict[str, Any]:
        status = "STOPPED" if stopped else "COMPLETED"
        with self.connection:
            batch = self.connection.execute(
                """SELECT id FROM browser_detail_enrichment_batches
                WHERE id = ? AND status = 'RUNNING'""",
                (batch_id,),
            ).fetchone()
            if batch is None:
                raise ValueError("detail batch is not RUNNING")
            unfinished = int(
                self.connection.execute(
                    """SELECT COUNT(*) FROM browser_detail_enrichment_queue
                    WHERE active_batch_id = ? AND status IN (
                      'DETAIL_PENDING', 'DETAIL_PROCESSING'
                    )""",
                    (batch_id,),
                ).fetchone()[0]
            )
            if unfinished and not stopped:
                raise ValueError("detail batch has unfinished queue items")
            if stopped:
                self.connection.execute(
                    """UPDATE browser_detail_enrichment_queue SET
                    status = 'DETAIL_PENDING', active_batch_id = NULL, claimed_at = NULL,
                    last_error_code = NULL, last_error_type = NULL,
                    last_error_reason = NULL, updated_at = ?
                    WHERE active_batch_id = ? AND status IN (
                      'DETAIL_PENDING', 'DETAIL_PROCESSING'
                    )""",
                    (completed_at or _utc_now(), batch_id),
                )
            cursor = self.connection.execute(
                """UPDATE browser_detail_enrichment_batches SET status = ?, completed_at = ?
                WHERE id = ? AND status = 'RUNNING'""",
                (status, completed_at or _utc_now(), batch_id),
            )
        if cursor.rowcount != 1:
            raise ValueError("detail batch is not RUNNING")
        return self.browser_detail_batch_summary(batch_id)

    def enqueue_browser_detail(self, post_url: str, *, enqueued_at: Optional[str] = None) -> int:
        """Durably enqueue one pending/failed identity; repeated enqueue is idempotent."""
        canonical_url = canonical_threads_post_url(post_url)
        if canonical_url != post_url:
            raise ValueError("post_url must already be canonical")
        identity = self.connection.execute(
            """SELECT id, status, current_observation_id FROM browser_post_identities
            WHERE post_url = ?""",
            (canonical_url,),
        ).fetchone()
        if identity is None:
            raise KeyError("browser post identity not found: " + canonical_url)
        if identity["status"] not in {"DETAIL_PENDING", "DETAIL_FAILED"}:
            raise ValueError("browser post is not awaiting detail enrichment")
        if identity["current_observation_id"] is None:
            raise ValueError("detail queue requires a source observation")
        timestamp = enqueued_at or _utc_now()
        with self.connection:
            existing = self.connection.execute(
                """SELECT id, status, enrichment_excluded
                FROM browser_detail_enrichment_queue
                WHERE browser_post_identity_id = ?""",
                (identity["id"],),
            ).fetchone()
            if existing is None:
                cursor = self.connection.execute(
                    """INSERT INTO browser_detail_enrichment_queue
                    (browser_post_identity_id, source_observation_id, status,
                     enqueued_at, updated_at)
                    VALUES (?, ?, 'DETAIL_PENDING', ?, ?)""",
                    (identity["id"], identity["current_observation_id"], timestamp, timestamp),
                )
                if cursor.lastrowid is None:
                    raise RuntimeError("SQLite did not return a detail queue id")
                return int(cursor.lastrowid)
            if bool(existing["enrichment_excluded"]):
                raise ValueError("browser detail enrichment is explicitly excluded")
            if existing["status"] == "DETAIL_FAILED":
                self.connection.execute(
                    """UPDATE browser_detail_enrichment_queue SET
                    status = 'DETAIL_PENDING', claimed_at = NULL,
                    active_batch_id = NULL, last_error_code = NULL,
                    last_error_type = NULL, last_error_reason = NULL, updated_at = ?
                    WHERE id = ?""",
                    (timestamp, existing["id"]),
                )
            return int(existing["id"])

    def exclude_browser_detail_enrichment(
        self, post_url: str, *, excluded_at: Optional[str] = None
    ) -> Dict[str, Any]:
        """Exclude one human-selected root without deleting any Source Store evidence."""
        canonical_url = canonical_threads_post_url(post_url)
        if canonical_url != post_url:
            raise ValueError("post_url must already be canonical")
        timestamp = excluded_at or _utc_now()
        with self.connection:
            row = self.connection.execute(
                """SELECT browser_detail_enrichment_queue.*
                FROM browser_detail_enrichment_queue
                JOIN browser_post_identities ON browser_post_identities.id =
                  browser_detail_enrichment_queue.browser_post_identity_id
                WHERE browser_post_identities.post_url = ?
                  AND EXISTS (
                    SELECT 1 FROM browser_observations
                    WHERE browser_observations.browser_post_identity_id =
                      browser_post_identities.id
                      AND browser_observations.observation_type = 'SEARCH_CARD'
                  )""",
                (canonical_url,),
            ).fetchone()
            if row is None:
                raise KeyError("collected root queue item not found: " + canonical_url)
            if row["status"] == "DETAIL_PROCESSING":
                raise ValueError("DETAIL_PROCESSING item cannot be excluded")
            if bool(row["enrichment_excluded"]):
                return {"queue_item_id": int(row["id"]), "changed": False, "excluded": True}
            self.connection.execute(
                """UPDATE browser_detail_enrichment_queue SET
                enrichment_excluded = 1,
                exclusion_reason = 'USER_EXCLUDED_SOURCE_UNAVAILABLE',
                excluded_at = ?, updated_at = ? WHERE id = ?""",
                (timestamp, timestamp, row["id"]),
            )
            self.connection.execute(
                """INSERT INTO browser_detail_enrichment_exclusion_actions
                (browser_detail_queue_id, action, exclusion_reason, acted_at)
                VALUES (?, 'EXCLUDED', 'USER_EXCLUDED_SOURCE_UNAVAILABLE', ?)""",
                (row["id"], timestamp),
            )
        return {"queue_item_id": int(row["id"]), "changed": True, "excluded": True}

    def requeue_browser_detail_enrichment(
        self, post_url: str, *, requeued_at: Optional[str] = None
    ) -> Dict[str, Any]:
        """Explicitly re-enable/requeue one root while retaining immutable history."""
        canonical_url = canonical_threads_post_url(post_url)
        if canonical_url != post_url:
            raise ValueError("post_url must already be canonical")
        timestamp = requeued_at or _utc_now()
        with self.connection:
            row = self.connection.execute(
                """SELECT browser_detail_enrichment_queue.*,
                          browser_post_identities.id AS identity_id
                FROM browser_detail_enrichment_queue
                JOIN browser_post_identities ON browser_post_identities.id =
                  browser_detail_enrichment_queue.browser_post_identity_id
                WHERE browser_post_identities.post_url = ?
                  AND EXISTS (
                    SELECT 1 FROM browser_observations
                    WHERE browser_observations.browser_post_identity_id =
                      browser_post_identities.id
                      AND browser_observations.observation_type = 'SEARCH_CARD'
                  )""",
                (canonical_url,),
            ).fetchone()
            if row is None:
                raise KeyError("collected root queue item not found: " + canonical_url)
            if row["status"] == "DETAIL_PROCESSING":
                raise ValueError("DETAIL_PROCESSING item cannot be requeued")
            was_excluded = bool(row["enrichment_excluded"])
            changed = was_excluded or row["status"] != "DETAIL_PENDING"
            if not changed:
                return {"queue_item_id": int(row["id"]), "changed": False, "excluded": False}
            self.connection.execute(
                """UPDATE browser_detail_enrichment_queue SET
                status = 'DETAIL_PENDING', active_batch_id = NULL, claimed_at = NULL,
                last_error_code = NULL, last_error_type = NULL, last_error_reason = NULL,
                enrichment_excluded = 0, exclusion_reason = NULL, excluded_at = NULL,
                updated_at = ? WHERE id = ?""",
                (timestamp, row["id"]),
            )
            self.connection.execute(
                """UPDATE browser_post_identities SET status = 'DETAIL_PENDING', updated_at = ?
                WHERE id = ?""",
                (timestamp, row["identity_id"]),
            )
            self.connection.execute(
                """INSERT INTO browser_detail_enrichment_exclusion_actions
                (browser_detail_queue_id, action, exclusion_reason, acted_at)
                VALUES (?, ?, NULL, ?)""",
                (row["id"], "RE_ENABLED" if was_excluded else "REQUEUED", timestamp),
            )
        return {"queue_item_id": int(row["id"]), "changed": True, "excluded": False}

    def requeue_invalid_browser_detail_text(self, *, requeued_at: Optional[str] = None) -> int:
        """Requeue enriched identities whose latest detail text is known date metadata.

        Source observations and their immutable quality assessments remain untouched. The
        durable queue keeps its original ``enqueued_at`` ordering so repaired collection
        revisits the oldest human-selected invalid evidence before newer pending work.
        """
        timestamp = requeued_at or _utc_now()
        with self.connection:
            rows = self.connection.execute(
                """SELECT browser_detail_enrichment_queue.id AS queue_id,
                          browser_post_identities.id AS identity_id
                   FROM browser_detail_enrichment_queue
                   JOIN browser_post_identities
                     ON browser_post_identities.id =
                        browser_detail_enrichment_queue.browser_post_identity_id
                   JOIN browser_observations
                     ON browser_observations.id =
                        browser_post_identities.current_observation_id
                    AND browser_observations.browser_post_identity_id =
                        browser_post_identities.id
                    AND browser_observations.observation_type = 'POST_DETAIL'
                   JOIN browser_text_quality_assessments
                     ON browser_text_quality_assessments.browser_observation_id =
                        browser_observations.id
                    AND browser_text_quality_assessments.quality_status =
                        'INVALID_TEXT_DATE_METADATA'
                    AND browser_text_quality_assessments.id = (
                      SELECT MAX(latest.id)
                      FROM browser_text_quality_assessments latest
                      WHERE latest.browser_observation_id = browser_observations.id)
                   WHERE browser_detail_enrichment_queue.status = 'DETAIL_ENRICHED'
                   ORDER BY browser_detail_enrichment_queue.id"""
            ).fetchall()
            queue_ids = [int(row["queue_id"]) for row in rows]
            identity_ids = [int(row["identity_id"]) for row in rows]
            if not queue_ids:
                return 0
            queue_placeholders = ",".join("?" for _ in queue_ids)
            identity_placeholders = ",".join("?" for _ in identity_ids)
            self.connection.execute(
                """UPDATE browser_detail_enrichment_queue SET
                   status = 'DETAIL_PENDING', active_batch_id = NULL, claimed_at = NULL,
                   last_error_code = NULL, last_error_type = NULL,
                   last_error_reason = NULL, updated_at = ?
                   WHERE id IN ({0})""".format(queue_placeholders),
                (timestamp, *queue_ids),
            )
            self.connection.execute(
                """UPDATE browser_post_identities SET status = 'DETAIL_PENDING',
                   updated_at = ? WHERE id IN ({0})""".format(identity_placeholders),
                (timestamp, *identity_ids),
            )
        return len(queue_ids)

    def requeue_browser_topic_tag_candidates(
        self, candidate_texts: Sequence[str], *, requeued_at: Optional[str] = None
    ) -> int:
        """Requeue possible legacy tag-only captures without declaring them invalid.

        A later v7 detail observation supplies the structural topic evidence used to
        confirm and append ``INVALID_TEXT_TOPIC_TAG_METADATA``. Exact text matching
        here changes queue state only and never changes source quality by itself.
        """
        candidates = {value.strip() for value in candidate_texts if value.strip()}
        if not candidates:
            return 0
        selected: List[sqlite3.Row] = []
        for row in self.connection.execute(
            """SELECT queue.id AS queue_id, identity.id AS identity_id,
                      observation.canonical_payload_json
               FROM browser_detail_enrichment_queue queue
               JOIN browser_post_identities identity
                 ON identity.id = queue.browser_post_identity_id
               JOIN browser_observations observation
                 ON observation.id = (
                   SELECT MAX(detail.id) FROM browser_observations detail
                   WHERE detail.browser_post_identity_id = identity.id
                     AND detail.observation_type = 'POST_DETAIL')
               WHERE queue.enrichment_excluded = 0
               ORDER BY queue.id"""
        ):
            payload = json.loads(row["canonical_payload_json"])
            if payload.get("text") in candidates:
                selected.append(row)
        if not selected:
            return 0
        timestamp = requeued_at or _utc_now()
        queue_ids = [int(row["queue_id"]) for row in selected]
        identity_ids = [int(row["identity_id"]) for row in selected]
        with self.connection:
            self.connection.execute(
                """UPDATE browser_detail_enrichment_queue SET
                   status = 'DETAIL_PENDING', active_batch_id = NULL, claimed_at = NULL,
                   last_error_code = NULL, last_error_type = NULL,
                   last_error_reason = NULL, updated_at = ?
                   WHERE id IN ({0})""".format(",".join("?" for _ in queue_ids)),
                (timestamp, *queue_ids),
            )
            self.connection.execute(
                """UPDATE browser_post_identities SET status = 'DETAIL_PENDING',
                   updated_at = ? WHERE id IN ({0})""".format(",".join("?" for _ in identity_ids)),
                (timestamp, *identity_ids),
            )
        return len(queue_ids)

    def reconcile_browser_topic_tag_text_quality(self) -> int:
        """Append confirmed legacy tag-only quality after either assessment order."""
        confirmed = 0
        repaired_rows = self.connection.execute(
            """SELECT id, browser_post_identity_id, canonical_payload_json, collected_at
            FROM browser_observations
            WHERE observation_type = 'POST_DETAIL'
              AND extractor_version = 'threads_post_detail_extractor_v7'
            ORDER BY id"""
        ).fetchall()
        with self.connection:
            for repaired in repaired_rows:
                repaired_payload = json.loads(repaired["canonical_payload_json"])
                topic_tags = repaired_payload.get("topic_tags", [])
                new_text = repaired_payload.get("text")
                if not isinstance(topic_tags, list) or not topic_tags:
                    continue
                for previous in self.connection.execute(
                    """SELECT old.id, old.canonical_payload_json,
                              (SELECT quality_status
                               FROM browser_text_quality_assessments quality
                               WHERE quality.browser_observation_id = old.id
                               ORDER BY quality.id DESC LIMIT 1) AS quality_status
                    FROM browser_observations old
                    WHERE old.browser_post_identity_id = ? AND old.id < ?
                      AND old.observation_type = 'POST_DETAIL'""",
                    (int(repaired["browser_post_identity_id"]), int(repaired["id"])),
                ).fetchall():
                    previous_payload = json.loads(previous["canonical_payload_json"])
                    previous_text = previous_payload.get("text")
                    if (
                        previous["quality_status"] not in (None, VALID_TEXT)
                        or not isinstance(previous_text, str)
                        or previous_text not in topic_tags
                        or previous_text == new_text
                    ):
                        continue
                    self.connection.execute(
                        """INSERT INTO browser_text_quality_assessments
                        (browser_observation_id, quality_status, assessor_version,
                         input_sha256, assessed_at)
                        VALUES (?, 'INVALID_TEXT_TOPIC_TAG_METADATA', ?, ?, ?)""",
                        (
                            int(previous["id"]),
                            "m4-browser-topic-tag-quality-v1",
                            hashlib.sha256(previous_text.encode("utf-8")).hexdigest(),
                            repaired["collected_at"],
                        ),
                    )
                    confirmed += 1
        return confirmed

    def claim_browser_detail(
        self, batch_id: int, *, claimed_at: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Atomically claim the oldest pending identity for one worker."""
        timestamp = claimed_at or _utc_now()
        with self.connection:
            batch = self.connection.execute(
                """SELECT * FROM browser_detail_enrichment_batches
                WHERE id = ? AND status = 'RUNNING'""",
                (batch_id,),
            ).fetchone()
            if batch is None:
                raise ValueError("detail batch is not RUNNING")
            assigned = int(
                self.connection.execute(
                    """SELECT COUNT(*) FROM browser_detail_enrichment_queue
                    WHERE active_batch_id = ?""",
                    (batch_id,),
                ).fetchone()[0]
            )
            row = self.connection.execute(
                """SELECT browser_detail_enrichment_queue.*, browser_post_identities.post_url
                FROM browser_detail_enrichment_queue
                JOIN browser_post_identities
                  ON browser_post_identities.id =
                     browser_detail_enrichment_queue.browser_post_identity_id
                WHERE browser_detail_enrichment_queue.status = 'DETAIL_PENDING'
                  AND browser_detail_enrichment_queue.enrichment_excluded = 0
                  AND (browser_detail_enrichment_queue.active_batch_id IS NULL
                       OR browser_detail_enrichment_queue.active_batch_id = ?)
                ORDER BY browser_detail_enrichment_queue.enqueued_at,
                         browser_detail_enrichment_queue.id LIMIT 1""",
                (batch_id,),
            ).fetchone()
            if row is None:
                return None
            if row["active_batch_id"] is None and assigned >= min(
                int(batch["requested_items"]), int(batch["max_items"])
            ):
                return None
            cursor = self.connection.execute(
                """UPDATE browser_detail_enrichment_queue SET
                status = 'DETAIL_PROCESSING', claimed_at = ?, updated_at = ?,
                active_batch_id = ?, lease_version = lease_version + 1,
                retry_count = retry_count + CASE WHEN attempt_count > 0 THEN 1 ELSE 0 END,
                attempt_count = attempt_count + 1
                WHERE id = ? AND status = 'DETAIL_PENDING'
                  AND enrichment_excluded = 0""",
                (timestamp, timestamp, batch_id, row["id"]),
            )
            if cursor.rowcount != 1:
                return None
            next_attempt = int(row["attempt_count"]) + 1
            next_lease = int(row["lease_version"]) + 1
            self.connection.execute(
                """INSERT INTO browser_detail_batch_assignments
                (browser_detail_batch_id, browser_detail_queue_id, attempt_count,
                 lease_version, assigned_at) VALUES (?, ?, ?, ?, ?)""",
                (batch_id, row["id"], next_attempt, next_lease, timestamp),
            )
            result = dict(row)
            result.update(
                status="DETAIL_PROCESSING",
                claimed_at=timestamp,
                attempt_count=next_attempt,
                retry_count=int(row["retry_count"]) + (1 if int(row["attempt_count"]) > 0 else 0),
                active_batch_id=batch_id,
                lease_version=next_lease,
            )
            result["queue_item_id"] = int(row["id"])
            result["batch_id"] = batch_id
            result["attempt"] = result["attempt_count"]
            return result

    def complete_browser_detail_queue(
        self,
        queue_id: int,
        *,
        batch_id: int,
        attempt: int,
        lease_version: int,
        detail_observation_id: int,
        completed_at: Optional[str] = None,
    ) -> None:
        """Complete claimed work only from matching persisted POST_DETAIL success evidence."""
        timestamp = completed_at or _utc_now()
        valid = self.connection.execute(
            """SELECT browser_detail_attempts.id AS attempt_id
            FROM browser_detail_enrichment_queue
            JOIN browser_observations
              ON browser_observations.id = ?
             AND browser_observations.browser_post_identity_id =
                 browser_detail_enrichment_queue.browser_post_identity_id
             AND browser_observations.observation_type = 'POST_DETAIL'
            JOIN browser_detail_attempts
              ON browser_detail_attempts.detail_observation_id = browser_observations.id
             AND browser_detail_attempts.outcome = 'SUCCEEDED'
            WHERE browser_detail_enrichment_queue.id = ?
              AND browser_detail_enrichment_queue.status = 'DETAIL_PROCESSING'
              AND browser_detail_enrichment_queue.active_batch_id = ?
              AND browser_detail_enrichment_queue.attempt_count = ?
              AND browser_detail_enrichment_queue.lease_version = ?""",
            (detail_observation_id, queue_id, batch_id, attempt, lease_version),
        ).fetchone()
        if valid is None:
            replay = self.connection.execute(
                """SELECT browser_detail_attempts.detail_observation_id
                FROM browser_detail_enrichment_queue
                JOIN browser_detail_attempts
                  ON browser_detail_attempts.id =
                     browser_detail_enrichment_queue.last_attempt_id
                WHERE browser_detail_enrichment_queue.id = ?
                  AND browser_detail_enrichment_queue.status = 'DETAIL_ENRICHED'
                  AND browser_detail_enrichment_queue.active_batch_id = ?
                  AND browser_detail_enrichment_queue.attempt_count = ?
                  AND browser_detail_enrichment_queue.lease_version = ?
                  AND browser_detail_attempts.detail_observation_id = ?""",
                (queue_id, batch_id, attempt, lease_version, detail_observation_id),
            ).fetchone()
            if replay is not None:
                return
            raise ValueError("detail completion evidence does not match claimed work")
        with self.connection:
            self.connection.execute(
                """UPDATE browser_detail_enrichment_queue SET
                status = 'DETAIL_ENRICHED', claimed_at = NULL,
                last_attempt_id = ?, updated_at = ?
                WHERE id = ? AND status = 'DETAIL_PROCESSING'""",
                (valid["attempt_id"], timestamp, queue_id),
            )

    def fail_browser_detail_queue(
        self,
        queue_id: int,
        *,
        batch_id: int,
        attempt: int,
        lease_version: int,
        attempted_at: str,
        extractor_version: str,
        failure_type: str,
        failure_reason: str,
        error_code: str,
        contract_version: str = DETAIL_ATTEMPT_CONTRACT_VERSION,
    ) -> int:
        """Atomically append bounded failure evidence and mark claimed work failed."""
        validate_detail_attempt_provenance(
            attempted_at=attempted_at,
            extractor_version=extractor_version,
            contract_version=contract_version,
        )
        validate_detail_failure(failure_type, failure_reason)
        error_codes = {
            "PAGE_TIMEOUT",
            "POST_NOT_FOUND",
            "ACTIVITY_BUTTON_NOT_FOUND",
            "ACTIVITY_DIALOG_TIMEOUT",
            "VIEW_COUNT_NOT_FOUND",
            "THREAD_SEQUENCE_NOT_OBSERVED",
            "INGESTION_FAILED",
            "EXTRACTOR_MISMATCH",
        }
        if error_code not in error_codes:
            raise ValueError("detail queue error code is invalid")
        queue = self.connection.execute(
            """SELECT browser_detail_enrichment_queue.*, browser_post_identities.post_url
            FROM browser_detail_enrichment_queue
            JOIN browser_post_identities
              ON browser_post_identities.id =
                 browser_detail_enrichment_queue.browser_post_identity_id
            WHERE browser_detail_enrichment_queue.id = ?
              AND browser_detail_enrichment_queue.status = 'DETAIL_PROCESSING'
              AND browser_detail_enrichment_queue.active_batch_id = ?
              AND browser_detail_enrichment_queue.attempt_count = ?
              AND browser_detail_enrichment_queue.lease_version = ?""",
            (queue_id, batch_id, attempt, lease_version),
        ).fetchone()
        if queue is None:
            raise ValueError("detail queue item is not DETAIL_PROCESSING")
        with self.connection:
            cursor = self.connection.execute(
                """INSERT INTO browser_detail_attempts
                (browser_post_identity_id, post_url, attempted_at, extractor_version,
                 contract_version, outcome, detail_observation_id)
                VALUES (?, ?, ?, ?, ?, 'FAILED', NULL)""",
                (
                    queue["browser_post_identity_id"],
                    queue["post_url"],
                    attempted_at,
                    extractor_version,
                    contract_version,
                ),
            )
            if cursor.lastrowid is None:
                raise RuntimeError("SQLite did not return a browser detail attempt id")
            attempt_id = int(cursor.lastrowid)
            self.connection.execute(
                """INSERT INTO browser_detail_failures
                (browser_detail_attempt_id, failure_type, failure_reason) VALUES (?, ?, ?)""",
                (attempt_id, failure_type, failure_reason),
            )
            self.connection.execute(
                """UPDATE browser_detail_enrichment_queue SET
                status = 'DETAIL_FAILED', claimed_at = NULL, last_attempt_id = ?,
                last_error_code = ?, last_error_type = ?, last_error_reason = ?,
                updated_at = ? WHERE id = ?""",
                (attempt_id, error_code, failure_type, failure_reason, attempted_at, queue_id),
            )
            self.connection.execute(
                """UPDATE browser_post_identities SET status = 'DETAIL_FAILED', updated_at = ?
                WHERE id = ? AND status != 'DETAIL_ENRICHED'""",
                (attempted_at, queue["browser_post_identity_id"]),
            )
        return attempt_id

    def recover_browser_detail_queue(
        self, *, claimed_before: str, recovered_at: Optional[str] = None
    ) -> int:
        """Return stale DETAIL_PROCESSING work to pending without inventing an attempt."""
        timestamp = recovered_at or _utc_now()
        with self.connection:
            cursor = self.connection.execute(
                """UPDATE browser_detail_enrichment_queue SET
                status = 'DETAIL_PENDING', claimed_at = NULL, last_error_code = NULL,
                last_error_type = NULL, last_error_reason = NULL, updated_at = ?
                WHERE status = 'DETAIL_PROCESSING' AND claimed_at < ?""",
                (timestamp, claimed_before),
            )
        return int(cursor.rowcount)

    def list_browser_pending_detail_urls(self, *, limit: int) -> Sequence[str]:
        """Return only canonical URL identities currently awaiting explicit detail work."""
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ValueError("pending detail limit must be between 1 and 100")
        rows = self.connection.execute(
            """SELECT browser_post_identities.post_url
            FROM browser_post_identities
            JOIN browser_detail_enrichment_queue ON
              browser_detail_enrichment_queue.browser_post_identity_id =
              browser_post_identities.id
            WHERE browser_post_identities.status = 'DETAIL_PENDING'
              AND browser_detail_enrichment_queue.status = 'DETAIL_PENDING'
              AND browser_detail_enrichment_queue.enrichment_excluded = 0
            ORDER BY browser_post_identities.updated_at,
                     browser_post_identities.id LIMIT ?""",
            (limit,),
        ).fetchall()
        return [str(row["post_url"]) for row in rows]

    def list_collected_browser_roots(
        self, *, status_filter: str = "ALL", sort: str = "newest", limit: int = 200
    ) -> Sequence[Dict[str, Any]]:
        """Return local review metadata for human-selected roots without source text."""
        allowed_filters = {"ALL", "DETAIL_PENDING", "DETAIL_FAILED", "DETAIL_ENRICHED", "EXCLUDED"}
        if status_filter not in allowed_filters:
            raise ValueError("invalid collected-root status filter")
        if sort not in {"newest", "oldest", "error_first"}:
            raise ValueError("invalid collected-root sort")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
            raise ValueError("collected-root limit must be between 1 and 500")
        where = ""
        parameters: list[Any] = []
        if status_filter == "EXCLUDED":
            where = "AND queue.enrichment_excluded = 1"
        elif status_filter != "ALL":
            where = "AND queue.enrichment_excluded = 0 AND queue.status = ?"
            parameters.append(status_filter)
        order = {
            "newest": "collected_at DESC, identity.id DESC",
            "oldest": "collected_at ASC, identity.id ASC",
            "error_first": (
                "CASE WHEN queue.last_error_code IS NULL THEN 1 ELSE 0 END, "
                "collected_at DESC, identity.id DESC"
            ),
        }[sort]
        rows = self.connection.execute(
            """SELECT identity.id AS identity_id, identity.post_url,
                      queue.status AS queue_status, queue.attempt_count,
                      queue.last_error_code, queue.enrichment_excluded,
                      queue.exclusion_reason, queue.excluded_at,
                      MIN(search.collected_at) AS collected_at
            FROM browser_post_identities AS identity
            JOIN browser_detail_enrichment_queue AS queue
              ON queue.browser_post_identity_id = identity.id
            JOIN browser_observations AS search
              ON search.browser_post_identity_id = identity.id
             AND search.observation_type = 'SEARCH_CARD'
            WHERE 1 = 1 {0}
            GROUP BY identity.id, identity.post_url, queue.status, queue.attempt_count,
                     queue.last_error_code, queue.enrichment_excluded,
                     queue.exclusion_reason, queue.excluded_at
            ORDER BY {1} LIMIT ?""".format(where, order),
            (*parameters, limit),
        ).fetchall()
        result = []
        for row in rows:
            approximate = self.connection.execute(
                """SELECT approximate.display, approximate.normalized_approx,
                          approximate.view_band
                FROM browser_approximate_view_observations AS approximate
                JOIN browser_observations AS observation
                  ON observation.id = approximate.browser_observation_id
                WHERE observation.browser_post_identity_id = ?
                ORDER BY approximate.observed_at DESC, approximate.id DESC LIMIT 1""",
                (row["identity_id"],),
            ).fetchone()
            latest_sequence = self.connection.execute(
                """SELECT detail_observation_id
                FROM browser_thread_sequence_observations
                WHERE root_browser_post_identity_id = ?
                  AND sequence_position = 0
                  AND relationship_evidence = 'ROOT_DETAIL_PAGE'
                ORDER BY observed_at DESC, id DESC LIMIT 1""",
                (row["identity_id"],),
            ).fetchone()
            self_reply_count = None
            if latest_sequence is not None:
                self_reply_count = int(
                    self.connection.execute(
                        """SELECT COUNT(*)
                        FROM browser_thread_sequence_observations
                        WHERE detail_observation_id = ? AND sequence_position > 0
                          AND same_author_as_root = 1
                          AND relationship_evidence =
                            'DOM_CONTIGUOUS_ROOT_AUTHOR_CHAIN'""",
                        (latest_sequence["detail_observation_id"],),
                    ).fetchone()[0]
                )
            post_url = str(row["post_url"])
            username = post_url.split("/@", 1)[1].split("/post/", 1)[0]
            excluded = bool(row["enrichment_excluded"])
            result.append(
                {
                    "collected_at": str(row["collected_at"]),
                    "author_username": username,
                    "post_url": post_url,
                    "detail_status": "EXCLUDED" if excluded else str(row["queue_status"]),
                    "attempt_count": int(row["attempt_count"]),
                    "last_error": None
                    if row["last_error_code"] is None
                    else str(row["last_error_code"]),
                    "rounded_views_raw": None
                    if approximate is None
                    else str(approximate["display"]),
                    "rounded_views_normalized": None
                    if approximate is None
                    else int(approximate["normalized_approx"]),
                    "rounded_views_band": None
                    if approximate is None
                    else str(approximate["view_band"]),
                    "self_reply_count": self_reply_count,
                    "enrichment_excluded": excluded,
                    "exclusion_reason": None
                    if row["exclusion_reason"] is None
                    else str(row["exclusion_reason"]),
                    "excluded_at": None if row["excluded_at"] is None else str(row["excluded_at"]),
                }
            )
        return result

    def count(self, table: str) -> int:
        allowed = {
            "collection_runs",
            "raw_posts",
            "normalized_posts",
            "accounts",
            "thread_relationships",
            "analysis_runs",
            "post_analysis",
            "normalized_post_versions",
            "collection_batches",
            "collection_batch_queries",
            "collection_batch_runs",
            "dataset_snapshots",
            "dataset_members",
            "post_metric_observations",
            "analysis_batches",
            "analysis_batch_items",
            "first_line_features",
            "parent_ending_features",
            "patterns",
            "pattern_instances",
            "browser_post_identities",
            "browser_observations",
            "browser_observed_fields",
            "browser_metric_observation_statuses",
            "browser_approximate_view_observations",
            "browser_display_view_observations",
            "browser_normalized_versions",
            "browser_detail_attempts",
            "browser_detail_failures",
            "browser_normalized_bridges",
            "browser_detail_enrichment_queue",
            "browser_detail_enrichment_exclusion_actions",
            "browser_detail_batch_assignments",
            "browser_detail_enrichment_batches",
            "m4_intelligence_runs",
            "m4_intelligence_instances",
            "m4_metric_snapshots",
            "m4_sequence_patterns",
            "m4_sequence_pattern_members",
            "browser_thread_sequence_observations",
            "structural_feature_runs",
            "structural_feature_instances",
            "structural_patterns",
            "structural_pattern_members",
            "browser_text_quality_assessments",
        }
        if table not in allowed:
            raise ValueError("Unsupported table")
        row: Optional[sqlite3.Row] = self.connection.execute(
            "SELECT COUNT(*) AS count FROM " + table
        ).fetchone()
        return int(row["count"]) if row else 0

    def create_m4_intelligence_run(
        self,
        dataset_snapshot_id: int,
        taxonomy_version: str,
        derivation_version: str,
        config: Dict[str, Any],
        *,
        created_at: Optional[str] = None,
    ) -> int:
        """Pin one finalized dataset to a closed M4 derivation configuration."""
        snapshot = self.connection.execute(
            "SELECT status FROM dataset_snapshots WHERE id = ?", (dataset_snapshot_id,)
        ).fetchone()
        if snapshot is None or snapshot["status"] != "FINALIZED":
            raise ValueError("M4 intelligence requires a finalized dataset")
        if not (
            _is_contract_identifier(taxonomy_version)
            and _is_contract_identifier(derivation_version)
        ):
            raise ValueError("M4 versions are invalid")
        config_json = _canonical_json(config)
        cursor = self.connection.execute(
            """INSERT INTO m4_intelligence_runs
            (dataset_snapshot_id, taxonomy_version, derivation_version, config_json,
             config_sha256, created_at) VALUES (?, ?, ?, ?, ?, ?)""",
            (
                dataset_snapshot_id,
                taxonomy_version,
                derivation_version,
                config_json,
                hashlib.sha256(config_json.encode("utf-8")).hexdigest(),
                created_at or _utc_now(),
            ),
        )
        self.connection.commit()
        if cursor.lastrowid is None:
            raise RuntimeError("SQLite did not return an M4 intelligence run id")
        return int(cursor.lastrowid)

    def create_structural_feature_run(
        self,
        dataset_snapshot_id: int,
        taxonomy_version: str,
        extractor_version: str,
        config: Dict[str, Any],
        *,
        created_at: Optional[str] = None,
    ) -> int:
        """Pin a finalized snapshot for deterministic structural extraction."""
        snapshot = self.connection.execute(
            "SELECT status FROM dataset_snapshots WHERE id = ?", (dataset_snapshot_id,)
        ).fetchone()
        if snapshot is None or snapshot["status"] != "FINALIZED":
            raise ValueError("structural extraction requires a finalized dataset")
        if not (
            _is_contract_identifier(taxonomy_version) and _is_contract_identifier(extractor_version)
        ):
            raise ValueError("structural versions are invalid")
        config_json = _canonical_json(config)
        cursor = self.connection.execute(
            """INSERT INTO structural_feature_runs
            (dataset_snapshot_id, taxonomy_version, extractor_version, config_json,
             config_sha256, created_at) VALUES (?, ?, ?, ?, ?, ?)""",
            (
                dataset_snapshot_id,
                taxonomy_version,
                extractor_version,
                config_json,
                hashlib.sha256(config_json.encode("utf-8")).hexdigest(),
                created_at or _utc_now(),
            ),
        )
        self.connection.commit()
        if cursor.lastrowid is None:
            raise RuntimeError("SQLite did not return a structural feature run id")
        return int(cursor.lastrowid)

    def persist_structural_feature_instance(
        self,
        *,
        structural_feature_run_id: int,
        normalized_post_version_id: int,
        feature: Dict[str, Any],
        input_sha256: str,
        created_at: Optional[str] = None,
    ) -> int:
        """Persist one text-free structural feature instance for a pinned source version."""
        _reject_pattern_leakage(feature)
        if not isinstance(input_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", input_sha256):
            raise ValueError("structural feature input hash is invalid")
        feature_json = _canonical_json(feature)
        cursor = self.connection.execute(
            """INSERT INTO structural_feature_instances
            (structural_feature_run_id, normalized_post_version_id, feature_json,
             feature_sha256, input_sha256, created_at) VALUES (?, ?, ?, ?, ?, ?)""",
            (
                structural_feature_run_id,
                normalized_post_version_id,
                feature_json,
                hashlib.sha256(feature_json.encode("utf-8")).hexdigest(),
                input_sha256,
                created_at or _utc_now(),
            ),
        )
        self.connection.commit()
        if cursor.lastrowid is None:
            raise RuntimeError("SQLite did not return a structural feature instance id")
        return int(cursor.lastrowid)

    def persist_m4_intelligence_instance(
        self,
        *,
        m4_intelligence_run_id: int,
        normalized_post_version_id: int,
        analysis_run_row_id: int,
        first_line_feature_id: int,
        parent_ending_feature_id: int,
        feature: Dict[str, Any],
        input_sha256: str,
        created_at: Optional[str] = None,
    ) -> int:
        """Append a closed, source-text-free M4 feature instance."""
        _reject_pattern_leakage(feature)
        if not isinstance(input_sha256, str) or len(input_sha256) != 64:
            raise ValueError("M4 instance input hash is invalid")
        feature_json = _canonical_json(feature)
        cursor = self.connection.execute(
            """INSERT INTO m4_intelligence_instances
            (m4_intelligence_run_id, normalized_post_version_id, analysis_run_row_id,
             first_line_feature_id, parent_ending_feature_id, feature_json, feature_sha256,
             input_sha256, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                m4_intelligence_run_id,
                normalized_post_version_id,
                analysis_run_row_id,
                first_line_feature_id,
                parent_ending_feature_id,
                feature_json,
                hashlib.sha256(feature_json.encode("utf-8")).hexdigest(),
                input_sha256,
                created_at or _utc_now(),
            ),
        )
        self.connection.commit()
        if cursor.lastrowid is None:
            raise RuntimeError("SQLite did not return an M4 intelligence instance id")
        return int(cursor.lastrowid)

    def get_normalized_post(self, source_post_id: str, source: str = "threads") -> Dict[str, Any]:
        row = self.connection.execute(
            """SELECT normalized_posts.*, normalized_post_versions.version
                     AS normalized_post_version
            FROM normalized_posts
            JOIN normalized_post_versions
              ON normalized_post_versions.id = normalized_posts.current_version_id
            WHERE source = ? AND source_post_id = ?""",
            (source, source_post_id),
        ).fetchone()
        if row is None:
            raise KeyError("normalized post not found: " + source + "/" + source_post_id)
        return dict(row)

    def get_normalized_post_version(self, version_id: int) -> Dict[str, Any]:
        """Load the immutable canonical payload pinned by a dataset member."""
        row = self.connection.execute(
            """SELECT id, version, canonical_payload_json
            FROM normalized_post_versions WHERE id = ?""",
            (version_id,),
        ).fetchone()
        if row is None:
            raise KeyError("normalized post version not found: " + str(version_id))
        payload = json.loads(str(row["canonical_payload_json"]))
        if not isinstance(payload, dict):
            raise RuntimeError("normalized post version payload is not an object")
        result: Dict[str, Any] = dict(payload)
        result["normalized_post_version_id"] = int(row["id"])
        result["normalized_post_version"] = int(row["version"])
        return result

    def start_analysis_run(self, metadata: Dict[str, Any]) -> int:
        """Record an analyzer attempt before calling or validating an adapter."""
        columns = (
            "analysis_run_id",
            "source",
            "source_post_id",
            "normalized_post_version",
            "analyzer_version",
            "taxonomy_version",
            "prompt_version",
            "model_provider",
            "model_name",
            "model_parameters",
            "input_sha256",
            "analyzed_at",
        )
        values = tuple(metadata[name] for name in columns)
        version_id = metadata.get("normalized_post_version_id")
        version = self.connection.execute(
            """SELECT normalized_post_versions.id
            FROM normalized_posts
            JOIN normalized_post_versions
              ON normalized_post_versions.normalized_post_id = normalized_posts.id
            WHERE normalized_posts.source = ?
              AND normalized_posts.source_post_id = ?
              AND normalized_post_versions.version = ?
              AND (? IS NULL OR normalized_post_versions.id = ?)""",
            (
                metadata["source"],
                metadata["source_post_id"],
                metadata["normalized_post_version"],
                version_id,
                version_id,
            ),
        ).fetchone()
        if version is None:
            raise ValueError("normalized post version not found for analysis run")
        cursor = self.connection.execute(
            """INSERT INTO analysis_runs
            (analysis_run_id, source, source_post_id, normalized_post_version,
             analyzer_version, taxonomy_version, prompt_version, model_provider,
             model_name, model_parameters_json, input_sha256, analyzed_at,
             normalized_post_version_id, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'RUNNING')""",
            values[:9] + (_canonical_json(values[9]),) + values[10:] + (int(version["id"]),),
        )
        self.connection.commit()
        if cursor.lastrowid is None:
            raise RuntimeError("SQLite did not return an analysis run id")
        return int(cursor.lastrowid)

    def fail_analysis_run(self, row_id: int, error_code: str) -> None:
        self.connection.execute(
            "UPDATE analysis_runs SET status = 'FAILED', error_code = ? WHERE id = ?",
            (error_code, row_id),
        )
        self.connection.commit()

    def persist_analysis(
        self, row_id: int, source_post_id: str, payload: Dict[str, Any], output_sha256: str
    ) -> None:
        """Atomically persist one successful output without overwriting history."""
        normalized = self.connection.execute(
            """SELECT normalized_posts.id
            FROM analysis_runs
            JOIN normalized_posts
              ON normalized_posts.source = analysis_runs.source
             AND normalized_posts.source_post_id = analysis_runs.source_post_id
            WHERE analysis_runs.id = ?
              AND analysis_runs.source_post_id = ?
              AND analysis_runs.status = 'RUNNING'""",
            (row_id, source_post_id),
        ).fetchone()
        if normalized is None:
            raise ValueError("analysis run is not RUNNING for source post: " + source_post_id)
        with self.connection:
            self.connection.execute(
                """INSERT INTO post_analysis
                (analysis_run_row_id, normalized_post_id, payload_json, output_sha256)
                VALUES (?, ?, ?, ?)""",
                (
                    row_id,
                    int(normalized["id"]),
                    json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True),
                    output_sha256,
                ),
            )
            self.connection.execute(
                """UPDATE analysis_runs
                SET status = 'SUCCEEDED', output_sha256 = ?, error_code = NULL
                WHERE id = ? AND status = 'RUNNING'""",
                (output_sha256, row_id),
            )

    def find_reusable_analysis(self, identity: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Return an identical successful analysis, if one already exists."""
        row = self.connection.execute(
            """SELECT analysis_runs.id AS analysis_run_row_id,
                      analysis_runs.analysis_run_id, post_analysis.payload_json
            FROM analysis_runs
            JOIN post_analysis ON post_analysis.analysis_run_row_id = analysis_runs.id
            WHERE analysis_runs.source = ?
              AND analysis_runs.source_post_id = ?
              AND analysis_runs.analyzer_version = ?
              AND analysis_runs.taxonomy_version = ?
              AND analysis_runs.prompt_version = ?
              AND analysis_runs.model_provider = ?
              AND analysis_runs.model_name = ?
              AND analysis_runs.model_parameters_json = ?
              AND analysis_runs.input_sha256 = ?
              AND analysis_runs.normalized_post_version_id = ?
              AND analysis_runs.status = 'SUCCEEDED'
            ORDER BY analysis_runs.id DESC LIMIT 1""",
            (
                identity["source"],
                identity["source_post_id"],
                identity["analyzer_version"],
                identity["taxonomy_version"],
                identity["prompt_version"],
                identity["model_provider"],
                identity["model_name"],
                _canonical_json(identity["model_parameters"]),
                identity["input_sha256"],
                identity["normalized_post_version_id"],
            ),
        ).fetchone()
        if row is None:
            return None
        return {
            "analysis_run_row_id": int(row["analysis_run_row_id"]),
            "analysis_run_id": str(row["analysis_run_id"]),
            "payload": json.loads(str(row["payload_json"])),
        }

    def create_analysis_batch(
        self,
        batch_key: str,
        dataset_snapshot_id: int,
        config: Dict[str, Any],
        *,
        started_at: Optional[str] = None,
    ) -> int:
        """Create work items from an immutable finalized dataset snapshot."""
        snapshot = self.connection.execute(
            "SELECT status FROM dataset_snapshots WHERE id = ?", (dataset_snapshot_id,)
        ).fetchone()
        if snapshot is None or snapshot["status"] != "FINALIZED":
            raise ValueError("analysis batch requires a finalized dataset snapshot")
        parameters = config.get("model_parameters")
        if not isinstance(parameters, dict):
            raise ValueError("model_parameters must be an object")
        required = (
            "analyzer_version",
            "taxonomy_version",
            "prompt_version",
            "model_provider",
            "model_name",
        )
        if any(not isinstance(config.get(key), str) or not config[key] for key in required):
            raise ValueError("analysis batch configuration is incomplete")
        canonical_config = _canonical_json(config)
        config_sha256 = hashlib.sha256(canonical_config.encode("utf-8")).hexdigest()
        with self.connection:
            cursor = self.connection.execute(
                """INSERT INTO analysis_batches
                (batch_key, dataset_snapshot_id, analyzer_version, taxonomy_version,
                 prompt_version, model_provider, model_name, model_parameters_json,
                 config_sha256, status, started_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'RUNNING', ?)""",
                (
                    batch_key,
                    dataset_snapshot_id,
                    config["analyzer_version"],
                    config["taxonomy_version"],
                    config["prompt_version"],
                    config["model_provider"],
                    config["model_name"],
                    _canonical_json(parameters),
                    config_sha256,
                    started_at or _utc_now(),
                ),
            )
            if cursor.lastrowid is None:
                raise RuntimeError("SQLite did not return an analysis batch id")
            batch_id = int(cursor.lastrowid)
            self.connection.execute(
                """INSERT INTO analysis_batch_items
                (analysis_batch_id, normalized_post_version_id, status)
                SELECT ?, normalized_post_version_id, 'PENDING'
                FROM dataset_members WHERE dataset_snapshot_id = ? ORDER BY ordinal""",
                (batch_id, dataset_snapshot_id),
            )
        return batch_id

    def get_analysis_batch(self, batch_id: int) -> Dict[str, Any]:
        row = self.connection.execute(
            "SELECT * FROM analysis_batches WHERE id = ?", (batch_id,)
        ).fetchone()
        if row is None:
            raise KeyError("analysis batch not found: " + str(batch_id))
        result = dict(row)
        result["model_parameters"] = json.loads(str(result.pop("model_parameters_json")))
        return result

    def pending_analysis_batch_items(self, batch_id: int) -> Tuple[Dict[str, Any], ...]:
        rows = self.connection.execute(
            """SELECT * FROM analysis_batch_items
            WHERE analysis_batch_id = ? AND status != 'SUCCEEDED' ORDER BY id""",
            (batch_id,),
        ).fetchall()
        return tuple(dict(row) for row in rows)

    def restart_analysis_batch(self, batch_id: int) -> None:
        with self.connection:
            cursor = self.connection.execute(
                """UPDATE analysis_batches
                SET status = 'RUNNING', completed_at = NULL WHERE id = ?""",
                (batch_id,),
            )
            if cursor.rowcount != 1:
                raise KeyError("analysis batch not found: " + str(batch_id))
            self.connection.execute(
                """UPDATE analysis_batch_items
                SET status = 'FAILED', error_code = 'INTERRUPTED'
                WHERE analysis_batch_id = ? AND status = 'RUNNING'""",
                (batch_id,),
            )

    def start_analysis_batch_item(self, item_id: int, *, started_at: str) -> int:
        cursor = self.connection.execute(
            """UPDATE analysis_batch_items SET status = 'RUNNING', attempt = attempt + 1,
                       started_at = ?, completed_at = NULL, error_code = NULL
            WHERE id = ? AND status IN ('PENDING', 'FAILED')""",
            (started_at, item_id),
        )
        self.connection.commit()
        if cursor.rowcount != 1:
            raise ValueError("analysis batch item is not retryable")
        row = self.connection.execute(
            "SELECT attempt FROM analysis_batch_items WHERE id = ?", (item_id,)
        ).fetchone()
        return int(row["attempt"])

    def finish_analysis_batch_item(
        self, item_id: int, analysis_run_row_id: int, *, completed_at: str
    ) -> None:
        cursor = self.connection.execute(
            """UPDATE analysis_batch_items SET status = 'SUCCEEDED',
                       analysis_run_row_id = ?, completed_at = ?, error_code = NULL
            WHERE id = ? AND status = 'RUNNING'""",
            (analysis_run_row_id, completed_at, item_id),
        )
        self.connection.commit()
        if cursor.rowcount != 1:
            raise ValueError("analysis batch item is not running")

    def fail_analysis_batch_item(
        self,
        item_id: int,
        error_code: str,
        *,
        completed_at: str,
        analysis_run_row_id: Optional[int] = None,
    ) -> None:
        cursor = self.connection.execute(
            """UPDATE analysis_batch_items SET status = 'FAILED', error_code = ?,
                       analysis_run_row_id = ?, completed_at = ?
            WHERE id = ? AND status = 'RUNNING'""",
            (error_code, analysis_run_row_id, completed_at, item_id),
        )
        self.connection.commit()
        if cursor.rowcount != 1:
            raise ValueError("analysis batch item is not running")

    def finalize_analysis_batch(self, batch_id: int, *, completed_at: str) -> str:
        failed = int(
            self.connection.execute(
                """SELECT COUNT(*) FROM analysis_batch_items
                WHERE analysis_batch_id = ? AND status != 'SUCCEEDED'""",
                (batch_id,),
            ).fetchone()[0]
        )
        status = "PARTIAL_FAILED" if failed else "SUCCEEDED"
        self.connection.execute(
            "UPDATE analysis_batches SET status = ?, completed_at = ? WHERE id = ?",
            (status, completed_at, batch_id),
        )
        self.connection.commit()
        return status

    def get_analysis_feature_source(self, analysis_run_row_id: int) -> Dict[str, Any]:
        """Load a successful M1 result and its exact immutable normalized version."""
        row = self.connection.execute(
            """SELECT analysis_runs.*, post_analysis.payload_json,
                      normalized_post_versions.canonical_payload_json
            FROM analysis_runs
            JOIN post_analysis ON post_analysis.analysis_run_row_id = analysis_runs.id
            JOIN normalized_post_versions
              ON normalized_post_versions.id = analysis_runs.normalized_post_version_id
            WHERE analysis_runs.id = ? AND analysis_runs.status = 'SUCCEEDED'""",
            (analysis_run_row_id,),
        ).fetchone()
        if row is None:
            raise ValueError("feature extraction requires a successful analysis run")
        result = dict(row)
        result["analysis_payload"] = json.loads(str(result.pop("payload_json")))
        result["normalized_payload"] = json.loads(str(result.pop("canonical_payload_json")))
        return result

    def persist_first_line_feature(
        self,
        *,
        analysis_run_row_id: int,
        normalized_post_version_id: int,
        extractor_version: str,
        feature_contract_version: str,
        input_sha256: str,
        feature: Dict[str, Any],
        extracted_at: str,
    ) -> Dict[str, Any]:
        """Persist a source-text-free feature, replaying an identical extractor run."""
        forbidden = {"text", "quote", "source_text", "line_text"}

        def reject_source_text(value: Any) -> None:
            if isinstance(value, dict):
                if forbidden.intersection(value):
                    raise ValueError("first-line feature must not persist source text")
                for child in value.values():
                    reject_source_text(child)
            elif isinstance(value, list):
                for child in value:
                    reject_source_text(child)

        reject_source_text(feature)
        required_keys = {
            "availability",
            "start",
            "end",
            "text_sha256",
            "char_count",
            "terminal_mark",
            "hook_family",
            "hook_subtype",
            "curiosity_gap",
            "self_relevance",
            "target_specificity",
            "emotional_intensity",
            "contrarian_level",
            "read_more_pressure",
            "expected_action",
            "m1_action_labels",
            "m1_structure_labels",
        }
        if set(feature) != required_keys:
            raise ValueError("first-line feature fields do not match the closed contract")
        if feature["availability"] not in {"EMPTY", "OBSERVED"}:
            raise ValueError("invalid first-line availability")
        if feature["terminal_mark"] not in {
            "QUESTION",
            "EXCLAMATION",
            "COLON",
            "OTHER",
            "NONE",
        }:
            raise ValueError("invalid first-line terminal mark")
        if feature["hook_family"] not in {
            "EMPTY",
            "QUESTION",
            "CONTRARIAN",
            "TARGETED",
            "EMOTIONAL",
            "OPEN_LOOP",
            "STATEMENT",
        }:
            raise ValueError("invalid first-line hook family")
        if feature["hook_subtype"] not in {
            "EMPTY",
            "WHY_QUESTION",
            "DIRECT_QUESTION",
            "CONTRARIAN_ASSERTION",
            "AUDIENCE_CALL_OUT",
            "EMOTION_LED",
            "CONTINUATION_CUE",
            "PLAIN_STATEMENT",
        }:
            raise ValueError("invalid first-line hook subtype")
        if feature["expected_action"] not in {"NONE", "ANSWER", "READ_MORE", "REFLECT"}:
            raise ValueError("invalid first-line expected action")
        score_keys = {
            "curiosity_gap",
            "self_relevance",
            "target_specificity",
            "emotional_intensity",
            "contrarian_level",
            "read_more_pressure",
        }
        if any(feature[key] not in {0, 1, 2, 3, "UNKNOWN"} for key in score_keys):
            raise ValueError("invalid first-line marker score")
        feature_json = _canonical_json(feature)
        feature_sha256 = hashlib.sha256(feature_json.encode("utf-8")).hexdigest()
        existing = self.connection.execute(
            """SELECT * FROM first_line_features
            WHERE analysis_run_row_id = ? AND extractor_version = ?""",
            (analysis_run_row_id, extractor_version),
        ).fetchone()
        if existing is not None:
            if str(existing["feature_sha256"]) != feature_sha256:
                raise ValueError("first-line feature replay produced different output")
            replay = dict(existing)
            replay["feature"] = json.loads(str(replay.pop("feature_json")))
            replay["reused"] = True
            return replay
        cursor = self.connection.execute(
            """INSERT INTO first_line_features
            (analysis_run_row_id, normalized_post_version_id, extractor_version,
             feature_contract_version, input_sha256, feature_json, feature_sha256,
             extracted_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                analysis_run_row_id,
                normalized_post_version_id,
                extractor_version,
                feature_contract_version,
                input_sha256,
                feature_json,
                feature_sha256,
                extracted_at,
            ),
        )
        self.connection.commit()
        if cursor.lastrowid is None:
            raise RuntimeError("SQLite did not return a first-line feature id")
        return {
            "id": int(cursor.lastrowid),
            "feature": feature,
            "feature_sha256": feature_sha256,
            "reused": False,
        }

    def get_parent_ending_source(self, child_analysis_run_row_id: int) -> Dict[str, Any]:
        """Resolve parent evidence only through the thread_relationships SSOT."""
        child = self.get_analysis_feature_source(child_analysis_run_row_id)
        relationships = self.connection.execute(
            """SELECT DISTINCT parent_post_id FROM thread_relationships
            WHERE source = ? AND child_post_id = ? ORDER BY parent_post_id""",
            (child["source"], child["source_post_id"]),
        ).fetchall()
        result: Dict[str, Any] = {"child": child}
        if not relationships or (
            len(relationships) == 1 and relationships[0]["parent_post_id"] is None
        ):
            result["availability"] = "NO_PARENT"
            return result
        if len(relationships) != 1:
            result["availability"] = "RELATIONSHIP_AMBIGUOUS"
            return result
        parent_post_id = str(relationships[0]["parent_post_id"])
        parent = self.connection.execute(
            """SELECT normalized_post_versions.id AS normalized_post_version_id,
                      normalized_post_versions.canonical_payload_json
            FROM normalized_posts
            JOIN normalized_post_versions
              ON normalized_post_versions.id = normalized_posts.current_version_id
            WHERE normalized_posts.source = ? AND normalized_posts.source_post_id = ?""",
            (child["source"], parent_post_id),
        ).fetchone()
        result["parent_source_post_id"] = parent_post_id
        if parent is None:
            result["availability"] = "PARENT_TEXT_UNAVAILABLE"
            return result
        parent_version_id = int(parent["normalized_post_version_id"])
        parent_analysis = self.connection.execute(
            """SELECT analysis_runs.id, post_analysis.payload_json
            FROM analysis_runs
            JOIN post_analysis ON post_analysis.analysis_run_row_id = analysis_runs.id
            WHERE analysis_runs.source = ? AND analysis_runs.source_post_id = ?
              AND analysis_runs.normalized_post_version_id = ?
              AND analysis_runs.analyzer_version = ?
              AND analysis_runs.taxonomy_version = ?
              AND analysis_runs.status = 'SUCCEEDED'
            ORDER BY analysis_runs.id DESC LIMIT 1""",
            (
                child["source"],
                parent_post_id,
                parent_version_id,
                child["analyzer_version"],
                child["taxonomy_version"],
            ),
        ).fetchone()
        result.update(
            {
                "availability": "OBSERVED",
                "parent_normalized_post_version_id": parent_version_id,
                "parent_normalized_payload": json.loads(str(parent["canonical_payload_json"])),
                "parent_analysis_run_row_id": (
                    int(parent_analysis["id"]) if parent_analysis is not None else None
                ),
                "parent_analysis_payload": (
                    json.loads(str(parent_analysis["payload_json"]))
                    if parent_analysis is not None
                    else None
                ),
            }
        )
        return result

    def persist_parent_ending_feature(
        self,
        *,
        child_analysis_run_row_id: int,
        child_normalized_post_version_id: int,
        parent_normalized_post_version_id: Optional[int],
        parent_analysis_run_row_id: Optional[int],
        extractor_version: str,
        feature_contract_version: str,
        input_sha256: str,
        feature: Dict[str, Any],
        extracted_at: str,
    ) -> Dict[str, Any]:
        """Persist a replay-safe parent ending without source text or identity metadata."""
        forbidden = {
            "text",
            "quote",
            "source_text",
            "line_text",
            "permalink",
            "username",
        }

        def reject_forbidden(value: Any) -> None:
            if isinstance(value, dict):
                if forbidden.intersection(value):
                    raise ValueError("parent-ending feature must not persist source text")
                for child in value.values():
                    reject_forbidden(child)
            elif isinstance(value, list):
                for child in value:
                    reject_forbidden(child)

        reject_forbidden(feature)
        required_keys = {
            "availability",
            "windows",
            "terminal_mark",
            "open_loop_score",
            "closure_score",
            "continuation_desire",
            "cliffhanger_technique",
            "m1_action_labels",
            "m1_structure_labels",
        }
        if set(feature) != required_keys:
            raise ValueError("parent-ending feature fields do not match the closed contract")
        if feature["availability"] not in {
            "OBSERVED",
            "NO_PARENT",
            "PARENT_TEXT_UNAVAILABLE",
            "RELATIONSHIP_AMBIGUOUS",
        }:
            raise ValueError("invalid parent-ending availability")
        if feature["terminal_mark"] not in {
            "QUESTION",
            "EXCLAMATION",
            "COLON",
            "OTHER",
            "NONE",
        }:
            raise ValueError("invalid parent-ending terminal mark")
        if feature["cliffhanger_technique"] not in {
            "UNKNOWN",
            "EXPLICIT_CONTINUATION",
            "ELLIPSIS",
            "UNANSWERED_QUESTION",
            "COLON_LEAD_IN",
            "NONE",
        }:
            raise ValueError("invalid parent-ending cliffhanger technique")
        score_keys = {"open_loop_score", "closure_score", "continuation_desire"}
        if any(feature[key] not in {0, 1, 2, 3, "UNKNOWN"} for key in score_keys):
            raise ValueError("invalid parent-ending marker score")
        windows = feature["windows"]
        if not isinstance(windows, list) or len(windows) > 3:
            raise ValueError("invalid parent-ending windows")
        window_keys = {"non_empty_line_count", "start", "end", "text_sha256", "char_count"}
        if any(not isinstance(window, dict) or set(window) != window_keys for window in windows):
            raise ValueError("invalid parent-ending window fields")
        child_link = self.connection.execute(
            """SELECT 1 FROM analysis_runs WHERE id = ?
            AND normalized_post_version_id = ? AND status = 'SUCCEEDED'""",
            (child_analysis_run_row_id, child_normalized_post_version_id),
        ).fetchone()
        if child_link is None:
            raise ValueError("parent-ending child provenance is inconsistent")
        if parent_analysis_run_row_id is not None:
            parent_link = self.connection.execute(
                """SELECT 1 FROM analysis_runs WHERE id = ?
                AND normalized_post_version_id = ? AND status = 'SUCCEEDED'""",
                (parent_analysis_run_row_id, parent_normalized_post_version_id),
            ).fetchone()
            if parent_link is None:
                raise ValueError("parent-ending parent provenance is inconsistent")
        feature_json = _canonical_json(feature)
        feature_sha256 = hashlib.sha256(feature_json.encode("utf-8")).hexdigest()
        existing = self.connection.execute(
            """SELECT * FROM parent_ending_features
            WHERE child_analysis_run_row_id = ? AND extractor_version = ?""",
            (child_analysis_run_row_id, extractor_version),
        ).fetchone()
        if existing is not None:
            if str(existing["feature_sha256"]) != feature_sha256:
                raise ValueError("parent-ending feature replay produced different output")
            replay = dict(existing)
            replay["feature"] = json.loads(str(replay.pop("feature_json")))
            replay["reused"] = True
            return replay
        cursor = self.connection.execute(
            """INSERT INTO parent_ending_features
            (child_analysis_run_row_id, child_normalized_post_version_id,
             parent_normalized_post_version_id, parent_analysis_run_row_id,
             extractor_version, feature_contract_version, input_sha256, feature_json,
             feature_sha256, extracted_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                child_analysis_run_row_id,
                child_normalized_post_version_id,
                parent_normalized_post_version_id,
                parent_analysis_run_row_id,
                extractor_version,
                feature_contract_version,
                input_sha256,
                feature_json,
                feature_sha256,
                extracted_at,
            ),
        )
        self.connection.commit()
        if cursor.lastrowid is None:
            raise RuntimeError("SQLite did not return a parent-ending feature id")
        return {
            "id": int(cursor.lastrowid),
            "feature": feature,
            "feature_sha256": feature_sha256,
            "reused": False,
        }

    def create_pattern(
        self,
        *,
        pattern_key: str,
        version: int,
        feature_signature: Dict[str, Any],
        ranking: Dict[str, Any],
        provenance: Dict[str, Any],
        review_status: str,
        instances: Sequence[Dict[str, Any]],
        created_at: str,
        replace_derived: bool = False,
    ) -> int:
        """Persist one closed pattern backed by at least two distinct source posts."""
        if not _is_contract_identifier(pattern_key) or version < 1:
            raise ValueError("pattern identity is invalid")
        if review_status not in {"PENDING", "APPROVED", "REJECTED"}:
            raise ValueError("invalid pattern review status")
        _reject_pattern_leakage(feature_signature)
        _reject_pattern_leakage(ranking)
        _reject_pattern_leakage(provenance)
        _validate_pattern_signature(feature_signature)
        _validate_pattern_ranking(ranking)
        _validate_pattern_provenance(provenance)
        required_instance_keys = {
            "source",
            "source_post_id",
            "analysis_run_row_id",
            "normalized_post_version_id",
            "first_line_feature_id",
            "parent_ending_feature_id",
            "extractor_version",
            "feature_contract_version",
            "input_sha256",
            "feature",
            "created_at",
        }
        if any(set(instance) != required_instance_keys for instance in instances):
            raise ValueError("pattern instance fields do not match the closed contract")
        distinct_sources = {
            (instance["source"], instance["source_post_id"]) for instance in instances
        }
        if len(distinct_sources) < 2:
            raise ValueError("pattern requires at least two distinct source posts")
        dataset_snapshot_id = int(provenance["dataset_snapshot_id"])
        snapshot = self.connection.execute(
            "SELECT status FROM dataset_snapshots WHERE id = ?", (dataset_snapshot_id,)
        ).fetchone()
        if snapshot is None or snapshot["status"] != "FINALIZED":
            raise ValueError("pattern provenance requires a finalized dataset snapshot")
        validated_instances = []
        for instance in instances:
            feature = instance["feature"]
            if not isinstance(feature, dict):
                raise ValueError("pattern instance feature must be an object")
            _reject_pattern_leakage(feature)
            _validate_pattern_signature(feature)
            if feature != feature_signature:
                raise ValueError("pattern instance does not match the pattern signature")
            input_hash = instance["input_sha256"]
            if (
                not isinstance(input_hash, str)
                or len(input_hash) != 64
                or any(character not in "0123456789abcdef" for character in input_hash)
            ):
                raise ValueError("pattern instance input hash is invalid")
            if not _is_contract_identifier(instance["extractor_version"]) or not (
                _is_contract_identifier(instance["feature_contract_version"])
            ):
                raise ValueError("pattern instance contract version is invalid")
            link = self.connection.execute(
                """SELECT analysis_runs.input_sha256 AS analysis_input_sha256,
                          first_line_features.input_sha256 AS first_input_sha256,
                          first_line_features.feature_sha256 AS first_feature_sha256,
                          parent_ending_features.input_sha256 AS ending_input_sha256,
                          parent_ending_features.feature_sha256 AS ending_feature_sha256,
                          first_line_features.feature_json AS first_json,
                          parent_ending_features.feature_json AS ending_json,
                          normalized_post_versions.version AS normalized_version
                FROM analysis_runs
                JOIN normalized_post_versions
                  ON normalized_post_versions.id = analysis_runs.normalized_post_version_id
                JOIN normalized_posts
                  ON normalized_posts.id = normalized_post_versions.normalized_post_id
                JOIN first_line_features
                  ON first_line_features.id = ?
                 AND first_line_features.analysis_run_row_id = analysis_runs.id
                 AND first_line_features.normalized_post_version_id = normalized_post_versions.id
                JOIN parent_ending_features
                  ON parent_ending_features.id = ?
                 AND parent_ending_features.child_analysis_run_row_id = analysis_runs.id
                 AND parent_ending_features.child_normalized_post_version_id =
                     normalized_post_versions.id
                JOIN dataset_members
                  ON dataset_members.dataset_snapshot_id = ?
                 AND dataset_members.normalized_post_version_id = normalized_post_versions.id
                WHERE analysis_runs.id = ? AND analysis_runs.status = 'SUCCEEDED'
                  AND normalized_posts.source = ? AND normalized_posts.source_post_id = ?
                  AND normalized_post_versions.id = ?""",
                (
                    instance["first_line_feature_id"],
                    instance["parent_ending_feature_id"],
                    dataset_snapshot_id,
                    instance["analysis_run_row_id"],
                    instance["source"],
                    instance["source_post_id"],
                    instance["normalized_post_version_id"],
                ),
            ).fetchone()
            if link is None:
                raise ValueError("pattern instance provenance is inconsistent")
            first = json.loads(str(link["first_json"]))
            ending = json.loads(str(link["ending_json"]))
            derived = {
                "first_line_hook_family": first.get("hook_family"),
                "first_line_hook_subtype": first.get("hook_subtype"),
                "parent_ending_availability": ending.get("availability"),
                "parent_cliffhanger_technique": ending.get("cliffhanger_technique"),
            }
            if derived != feature:
                raise ValueError("pattern instance feature does not match feature evidence")
            expected_input_hash = pattern_instance_input_sha256(
                analysis_input_sha256=str(link["analysis_input_sha256"]),
                first_line_input_sha256=str(link["first_input_sha256"]),
                first_line_feature_sha256=str(link["first_feature_sha256"]),
                parent_ending_input_sha256=str(link["ending_input_sha256"]),
                parent_ending_feature_sha256=str(link["ending_feature_sha256"]),
            )
            if input_hash != expected_input_hash:
                raise ValueError("pattern instance input hash does not match feature evidence")
            feature_json = _canonical_json(feature)
            validated_instances.append(
                (
                    instance,
                    feature_json,
                    hashlib.sha256(feature_json.encode("utf-8")).hexdigest(),
                    int(link["normalized_version"]),
                )
            )
        signature_json = _canonical_json(feature_signature)
        expected_set_hash = pattern_set_input_sha256(
            [str(instance["input_sha256"]) for instance in instances], feature_signature
        )
        if provenance["input_sha256"] != expected_set_hash:
            raise ValueError("pattern provenance input hash does not match instance evidence")
        ranking_json = _canonical_json(ranking)
        provenance_json = _canonical_json(provenance)
        existing = self.connection.execute(
            "SELECT * FROM patterns WHERE pattern_key = ? AND version = ?",
            (pattern_key, version),
        ).fetchone()
        if existing is not None:
            existing_hashes = sorted(
                str(row["input_sha256"])
                for row in self.connection.execute(
                    "SELECT input_sha256 FROM pattern_instances WHERE pattern_id = ?",
                    (int(existing["id"]),),
                ).fetchall()
            )
            desired_hashes = sorted(str(instance["input_sha256"]) for instance in instances)
            unchanged = (
                str(existing["feature_signature_json"]) == signature_json
                and int(existing["member_count"]) == len(validated_instances)
                and str(existing["ranking_json"]) == ranking_json
                and str(existing["provenance_json"]) == provenance_json
                and existing_hashes == desired_hashes
            )
            if unchanged:
                return int(existing["id"])
            if not replace_derived:
                raise sqlite3.IntegrityError("pattern identity already exists")
        with self.connection:
            if existing is None:
                cursor = self.connection.execute(
                    """INSERT INTO patterns
                    (pattern_key, version, feature_signature_json, feature_signature_sha256,
                     member_count, ranking_json, provenance_json, review_status, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        pattern_key,
                        version,
                        signature_json,
                        hashlib.sha256(signature_json.encode("utf-8")).hexdigest(),
                        len(validated_instances),
                        ranking_json,
                        provenance_json,
                        review_status,
                        created_at,
                    ),
                )
                if cursor.lastrowid is None:
                    raise RuntimeError("SQLite did not return a pattern id")
                pattern_id = int(cursor.lastrowid)
            else:
                pattern_id = int(existing["id"])
                self.connection.execute(
                    """UPDATE patterns SET feature_signature_json = ?,
                              feature_signature_sha256 = ?, member_count = ?,
                              ranking_json = ?, provenance_json = ? WHERE id = ?""",
                    (
                        signature_json,
                        hashlib.sha256(signature_json.encode("utf-8")).hexdigest(),
                        len(validated_instances),
                        ranking_json,
                        provenance_json,
                        pattern_id,
                    ),
                )
                self.connection.execute(
                    "DELETE FROM pattern_instances WHERE pattern_id = ?", (pattern_id,)
                )
            for instance, feature_json, feature_sha256, normalized_version in validated_instances:
                self.connection.execute(
                    """INSERT INTO pattern_instances
                    (pattern_id, source, source_post_id, analysis_run_row_id,
                     normalized_post_version_id, normalized_version, first_line_feature_id,
                     parent_ending_feature_id, extractor_version,
                     feature_contract_version, input_sha256, feature_json, feature_sha256,
                     created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        pattern_id,
                        instance["source"],
                        instance["source_post_id"],
                        instance["analysis_run_row_id"],
                        instance["normalized_post_version_id"],
                        normalized_version,
                        instance["first_line_feature_id"],
                        instance["parent_ending_feature_id"],
                        instance["extractor_version"],
                        instance["feature_contract_version"],
                        instance["input_sha256"],
                        feature_json,
                        feature_sha256,
                        instance["created_at"],
                    ),
                )
        return pattern_id

    def review_pattern(self, pattern_id: int, review_status: str) -> None:
        if review_status not in {"APPROVED", "REJECTED"}:
            raise ValueError("review must approve or reject a pending pattern")
        cursor = self.connection.execute(
            """UPDATE patterns SET review_status = ?
            WHERE id = ? AND review_status = 'PENDING'""",
            (review_status, pattern_id),
        )
        self.connection.commit()
        if cursor.rowcount != 1:
            raise ValueError("pattern is not pending review")
