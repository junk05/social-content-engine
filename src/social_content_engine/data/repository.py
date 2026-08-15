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


MIGRATIONS: Tuple[Migration, ...] = (
    (1, "activate-m1-analyzer-tables-v1", _migration_1_activate_analyzer_tables),
    (2, "normalized-post-version-history-v1", _migration_2_normalized_versions),
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

    def count(self, table: str) -> int:
        allowed = {
            "collection_runs",
            "raw_posts",
            "normalized_posts",
            "accounts",
            "thread_relationships",
            "analysis_runs",
            "post_analysis",
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
        version = self.connection.execute(
            """SELECT normalized_post_versions.id
            FROM normalized_posts
            JOIN normalized_post_versions
              ON normalized_post_versions.normalized_post_id = normalized_posts.id
            WHERE normalized_posts.source = ?
              AND normalized_posts.source_post_id = ?
              AND normalized_post_versions.version = ?""",
            (metadata["source"], metadata["source_post_id"], metadata["normalized_post_version"]),
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
            """SELECT analysis_runs.analysis_run_id, post_analysis.payload_json
            FROM analysis_runs
            JOIN post_analysis ON post_analysis.analysis_run_row_id = analysis_runs.id
            WHERE analysis_runs.source = ?
              AND analysis_runs.source_post_id = ?
              AND analysis_runs.analyzer_version = ?
              AND analysis_runs.taxonomy_version = ?
              AND analysis_runs.prompt_version = ?
              AND analysis_runs.model_name = ?
              AND analysis_runs.model_parameters_json = ?
              AND analysis_runs.input_sha256 = ?
              AND analysis_runs.status = 'SUCCEEDED'
            ORDER BY analysis_runs.id DESC LIMIT 1""",
            (
                identity["source"],
                identity["source_post_id"],
                identity["analyzer_version"],
                identity["taxonomy_version"],
                identity["prompt_version"],
                identity["model_name"],
                json.dumps(identity["model_parameters"], ensure_ascii=False, sort_keys=True),
                identity["input_sha256"],
            ),
        ).fetchone()
        if row is None:
            return None
        return {
            "analysis_run_id": str(row["analysis_run_id"]),
            "payload": json.loads(str(row["payload_json"])),
        }
