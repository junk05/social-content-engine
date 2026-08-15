import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from social_content_engine.analyzer.mock_adapter import DeterministicMockAdapter
from social_content_engine.analyzer.orchestrator import analyze_post
from social_content_engine.data import repository as repository_module
from social_content_engine.data.repository import SCHEMA, Repository


def post(
    *,
    text: str = "version one",
    raw_sha256: str = "0" * 64,
    at: str = "2026-08-16T00:00:00+00:00",
) -> dict:
    return {
        "schema_version": 1,
        "source": "threads",
        "source_post_id": "post-1",
        "author_id": "account-1",
        "username": "fixture",
        "text": text,
        "permalink": "https://example.invalid/post-1",
        "published_at": "2026-08-16T00:00:00+00:00",
        "media_type": "TEXT_POST",
        "raw_sha256": raw_sha256,
        "normalized_at": at,
    }


def create_pre_m2_m1_database(path: Path, *, with_analysis: bool) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(SCHEMA)
    item = post()
    connection.execute(
        """INSERT INTO normalized_posts
        (source, source_post_id, author_id, username, text, permalink, published_at,
         media_type, raw_sha256, normalized_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        tuple(
            item[name]
            for name in (
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
        ),
    )
    if with_analysis:
        connection.execute(
            """INSERT INTO analysis_runs
            (analysis_run_id, source, source_post_id, normalized_post_version,
             analyzer_version, taxonomy_version, prompt_version, model_provider,
             model_name, model_parameters_json, input_sha256, output_sha256,
             analyzed_at, status, error_code)
            VALUES ('legacy-run', 'threads', 'post-1', 1, 'm1', 'taxonomy', 'prompt',
                    'deterministic', 'mock', '{}', ?, ?, ?, 'SUCCEEDED', NULL)""",
            ("1" * 64, "2" * 64, "2026-08-16T00:01:00+00:00"),
        )
        run_row_id = int(connection.execute("SELECT id FROM analysis_runs").fetchone()[0])
        normalized_id = int(connection.execute("SELECT id FROM normalized_posts").fetchone()[0])
        connection.execute(
            """INSERT INTO post_analysis
            (analysis_run_row_id, normalized_post_id, payload_json, output_sha256)
            VALUES (?, ?, '{}', ?)""",
            (run_row_id, normalized_id, "2" * 64),
        )
    connection.commit()
    connection.close()


def replace_analyzer_tables_with_m0_reserved_shape(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.execute("DROP TABLE post_analysis")
    connection.execute("DROP TABLE analysis_runs")
    connection.execute(
        """CREATE TABLE analysis_runs (
          id INTEGER PRIMARY KEY, analyzer_version TEXT NOT NULL,
          taxonomy_version TEXT NOT NULL, model TEXT NOT NULL,
          prompt_version TEXT NOT NULL, analyzed_at TEXT NOT NULL
        )"""
    )
    connection.execute(
        """CREATE TABLE post_analysis (
          id INTEGER PRIMARY KEY, analysis_run_id INTEGER NOT NULL,
          source_post_id TEXT NOT NULL, payload_json TEXT NOT NULL
        )"""
    )
    connection.commit()
    connection.close()


class RepositoryMigrationTest(unittest.TestCase):
    def test_backfills_legacy_m0_post_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.sqlite3"
            create_pre_m2_m1_database(path, with_analysis=False)
            replace_analyzer_tables_with_m0_reserved_shape(path)
            with Repository(path) as repository:
                version = repository.connection.execute(
                    "SELECT * FROM normalized_post_versions"
                ).fetchone()
                identity = repository.connection.execute(
                    "SELECT current_version_id FROM normalized_posts"
                ).fetchone()
                self.assertEqual(1, version["version"])
                self.assertEqual(version["id"], identity["current_version_id"])
                self.assertIsNone(version["source_raw_post_id"])
                first_migrations = repository.connection.execute(
                    "SELECT version, migration_sha256 FROM schema_migrations ORDER BY version"
                ).fetchall()
                analyzer_columns = {
                    row["name"]
                    for row in repository.connection.execute(
                        "PRAGMA table_info(analysis_runs)"
                    ).fetchall()
                }
                self.assertIn("analysis_run_id", analyzer_columns)
            with Repository(path) as repository:
                self.assertEqual(1, repository.count("normalized_posts"))
                self.assertEqual(1, repository.connection.execute(
                    "SELECT COUNT(*) FROM normalized_post_versions"
                ).fetchone()[0])
                second_migrations = repository.connection.execute(
                    "SELECT version, migration_sha256 FROM schema_migrations ORDER BY version"
                ).fetchall()
                self.assertEqual(
                    [tuple(row) for row in first_migrations],
                    [tuple(row) for row in second_migrations],
                )

    def test_backfills_existing_m1_analysis_to_version_one(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy-m1.sqlite3"
            create_pre_m2_m1_database(path, with_analysis=True)
            with Repository(path) as repository:
                row = repository.connection.execute(
                    """SELECT analysis_runs.normalized_post_version,
                              analysis_runs.normalized_post_version_id,
                              normalized_post_versions.version
                    FROM analysis_runs
                    JOIN normalized_post_versions
                      ON normalized_post_versions.id = analysis_runs.normalized_post_version_id"""
                ).fetchone()
                self.assertEqual((1, 1), (row["normalized_post_version"], row["version"]))
                self.assertIsNotNone(row["normalized_post_version_id"])
                self.assertEqual(1, repository.count("post_analysis"))

    def test_reuses_same_payload_and_versions_changed_payload(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with Repository(Path(directory) / "test.sqlite3") as repository:
                repository.upsert_normalized_post(post())
                repository.upsert_normalized_post(
                    post(at="2026-08-16T00:02:00+00:00")
                )
                self.assertEqual(1, repository.connection.execute(
                    "SELECT COUNT(*) FROM normalized_post_versions"
                ).fetchone()[0])
                repository.upsert_normalized_post(
                    post(text="version two", raw_sha256="3" * 64, at="2026-08-16T00:03:00+00:00")
                )
                versions = repository.connection.execute(
                    "SELECT id, version FROM normalized_post_versions ORDER BY version"
                ).fetchall()
                current = repository.connection.execute(
                    "SELECT text, current_version_id FROM normalized_posts"
                ).fetchone()
                self.assertEqual([1, 2], [row["version"] for row in versions])
                self.assertEqual("version two", current["text"])
                self.assertEqual(versions[1]["id"], current["current_version_id"])
                analysis = analyze_post(
                    repository,
                    "post-1",
                    DeterministicMockAdapter(),
                    now=lambda: "2026-08-16T00:04:00+00:00",
                    new_run_id=lambda: "version-two-run",
                )
                run = repository.connection.execute(
                    """SELECT normalized_post_version, normalized_post_version_id
                    FROM analysis_runs WHERE analysis_run_id = ?""",
                    (analysis.analysis_run_id,),
                ).fetchone()
                self.assertEqual(2, run["normalized_post_version"])
                self.assertEqual(versions[1]["id"], run["normalized_post_version_id"])

    def test_failed_migration_rolls_back_schema_and_record(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.sqlite3"
            with Repository(path):
                pass

            def fail(connection: sqlite3.Connection) -> None:
                connection.execute("CREATE TABLE should_roll_back (id INTEGER PRIMARY KEY)")
                raise RuntimeError("injected migration failure")

            failed_version = len(repository_module.MIGRATIONS) + 1
            migrations = repository_module.MIGRATIONS + (
                (failed_version, "injected-failure", fail),
            )
            with patch.object(repository_module, "MIGRATIONS", migrations):
                with self.assertRaisesRegex(RuntimeError, "injected migration failure"):
                    Repository(path)
            connection = sqlite3.connect(path)
            try:
                self.assertIsNone(
                    connection.execute(
                        "SELECT name FROM sqlite_master WHERE name = 'should_roll_back'"
                    ).fetchone()
                )
                self.assertEqual(
                    0,
                    connection.execute(
                        "SELECT COUNT(*) FROM schema_migrations WHERE version = ?",
                        (failed_version,),
                    ).fetchone()[0],
                )
            finally:
                connection.close()

    def test_foreign_keys_and_integrity_are_clean(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with Repository(Path(directory) / "test.sqlite3") as repository:
                repository.upsert_normalized_post(post())
                foreign_key_errors = repository.connection.execute(
                    "PRAGMA foreign_key_check"
                ).fetchall()
                integrity = repository.connection.execute("PRAGMA integrity_check").fetchone()[0]
                self.assertEqual([], foreign_key_errors)
                self.assertEqual("ok", integrity)


if __name__ == "__main__":
    unittest.main()
