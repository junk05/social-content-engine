"""SQLite implementation of the M0 repository boundary."""

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Sequence, Tuple

from .browser_observation import (
    BROWSER_NORMALIZER_VERSION,
    browser_normalized_payload,
    browser_observation_status,
    canonical_browser_normalized_payload,
    validate_browser_observation,
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
        "feature_signature_sha256": hashlib.sha256(
            signature_json.encode("utf-8")
        ).hexdigest(),
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
    return isinstance(value, str) and 0 < len(value) <= 128 and all(
        character in allowed for character in value
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
    if not isinstance(value, str) or len(value) != 64 or any(
        character not in "0123456789abcdef" for character in value
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


MIGRATIONS: Tuple[Migration, ...] = (
    (1, "activate-m1-analyzer-tables-v1", _migration_1_activate_analyzer_tables),
    (2, "normalized-post-version-history-v1", _migration_2_normalized_versions),
    (3, "collection-batches-datasets-metric-observations-v1", _migration_3_dataset_expansion),
    (4, "analysis-batches-pinned-dataset-versions-v1", _migration_4_analysis_batches),
    (5, "first-line-features-no-source-text-v1", _migration_5_first_line_features),
    (6, "parent-ending-features-thread-relationships-v1", _migration_6_parent_ending_features),
    (7, "closed-pattern-evidence-contract-v1", _migration_7_pattern_evidence_contract),
    (8, "browser-observations-url-identity-v1", _migration_8_browser_observations),
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

    def add_collection_batch_query(
        self, batch_id: int, ordinal: int, query: Dict[str, Any]
    ) -> int:
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

    def add_browser_observation(self, observation: Dict[str, Any]) -> Dict[str, Any]:
        """Append one closed browser observation and version its normalized projection."""
        canonical_url = validate_browser_observation(observation)
        status = browser_observation_status(observation)
        source_post_id = observation.get("source_post_id")
        canonical_observation_json = _canonical_json(observation)
        fields = observation["observed_fields"]
        field_provenance_json = json.dumps(
            fields, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True
        )
        field_provenance_sha256 = hashlib.sha256(
            field_provenance_json.encode("utf-8")
        ).hexdigest()
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
        return {
            "browser_post_identity_id": identity_id,
            "browser_observation_id": observation_id,
            "browser_normalized_version_id": version_id,
            "browser_normalized_version": version_number,
            "normalized_version_reused": reused,
            "status": status,
            "post_url": canonical_url,
        }

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
            "browser_normalized_versions",
        }
        if table not in allowed:
            raise ValueError("Unsupported table")
        row: Optional[sqlite3.Row] = self.connection.execute(
            "SELECT COUNT(*) AS count FROM " + table
        ).fetchone()
        return int(row["count"]) if row else 0

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
            values[:9]
            + (_canonical_json(values[9]),)
            + values[10:]
            + (int(version["id"]),),
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
        result["normalized_payload"] = json.loads(
            str(result.pop("canonical_payload_json"))
        )
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
                "parent_normalized_payload": json.loads(
                    str(parent["canonical_payload_json"])
                ),
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
            if not isinstance(input_hash, str) or len(input_hash) != 64 or any(
                character not in "0123456789abcdef" for character in input_hash
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
