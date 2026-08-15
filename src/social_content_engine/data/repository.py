"""SQLite implementation of the M0 repository boundary."""

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, Optional

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


class Repository:
    """Persist evidence and normalized derivatives through a small stable API."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.connection = sqlite3.connect(str(path))
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(SCHEMA)
        self._migrate_reserved_analyzer_tables()

    def _migrate_reserved_analyzer_tables(self) -> None:
        columns = {
            str(row["name"])
            for row in self.connection.execute("PRAGMA table_info(analysis_runs)").fetchall()
        }
        if "analysis_run_id" in columns:
            return
        count = self.connection.execute("SELECT COUNT(*) FROM analysis_runs").fetchone()[0]
        if count:
            raise RuntimeError("legacy analysis_runs contains data; automatic migration refused")
        self.connection.executescript(
            """
            DROP TABLE post_analysis;
            DROP TABLE analysis_runs;
            CREATE TABLE analysis_runs (
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
            );
            CREATE TABLE post_analysis (
              id INTEGER PRIMARY KEY,
              analysis_run_row_id INTEGER NOT NULL UNIQUE REFERENCES analysis_runs(id),
              normalized_post_id INTEGER NOT NULL REFERENCES normalized_posts(id),
              payload_json TEXT NOT NULL,
              output_sha256 TEXT NOT NULL
            );
            """
        )

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
    ) -> None:
        self.connection.execute(
            """INSERT OR IGNORE INTO raw_posts
            (collection_run_id, source, source_post_id, raw_json, raw_sha256, retrieved_at)
            VALUES (?, 'threads', ?, ?, ?, ?)""",
            (collection_run_id, source_post_id, raw_json, raw_sha256, retrieved_at),
        )
        self.connection.commit()

    def upsert_normalized_post(self, post: Dict[str, Any]) -> None:
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
        self.connection.execute(
            """INSERT INTO normalized_posts
            (source, source_post_id, author_id, username, text, permalink, published_at,
             media_type, raw_sha256, normalized_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source, source_post_id) DO UPDATE SET
              author_id=excluded.author_id, username=excluded.username, text=excluded.text,
              permalink=excluded.permalink, published_at=excluded.published_at,
              media_type=excluded.media_type, raw_sha256=excluded.raw_sha256,
              normalized_at=excluded.normalized_at""",
            values,
        )
        self.connection.commit()

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
            "SELECT * FROM normalized_posts WHERE source = ? AND source_post_id = ?",
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
        cursor = self.connection.execute(
            """INSERT INTO analysis_runs
            (analysis_run_id, source, source_post_id, normalized_post_version,
             analyzer_version, taxonomy_version, prompt_version, model_provider,
             model_name, model_parameters_json, input_sha256, analyzed_at, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'RUNNING')""",
            values[:9]
            + (json.dumps(values[9], ensure_ascii=False, sort_keys=True),)
            + values[10:],
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
