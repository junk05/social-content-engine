"""SQLite implementation of the M0 repository boundary."""

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

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


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _canonical_json(document: Dict[str, Any]) -> str:
    return json.dumps(
        document, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True
    )


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


MIGRATIONS: Tuple[Migration, ...] = (
    (1, "activate-m1-analyzer-tables-v1", _migration_1_activate_analyzer_tables),
    (2, "normalized-post-version-history-v1", _migration_2_normalized_versions),
    (3, "collection-batches-datasets-metric-observations-v1", _migration_3_dataset_expansion),
    (4, "analysis-batches-pinned-dataset-versions-v1", _migration_4_analysis_batches),
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
            + (json.dumps(values[9], ensure_ascii=False, sort_keys=True),)
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
                json.dumps(identity["model_parameters"], ensure_ascii=False, sort_keys=True),
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
