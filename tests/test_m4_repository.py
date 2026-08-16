import tempfile
import unittest
from pathlib import Path

from social_content_engine.data.repository import Repository


class M4RepositoryTest(unittest.TestCase):
    def test_m4_tables_are_additive_and_migration_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "m4.sqlite3"
            with Repository(path) as repository:
                tables = {
                    row["name"]
                    for row in repository.connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    ).fetchall()
                }
                self.assertTrue(
                    {
                        "m4_intelligence_runs", "m4_intelligence_instances", "m4_metric_snapshots",
                        "m4_sequence_patterns", "m4_sequence_pattern_members",
                        "structural_feature_runs", "structural_feature_instances",
                        "structural_patterns", "structural_pattern_members",
                    }
                    .issubset(tables)
                )
                migration = repository.connection.execute(
                    "SELECT migration_sha256 FROM schema_migrations WHERE version = 11"
                ).fetchone()
                self.assertRegex(migration["migration_sha256"], r"^[0-9a-f]{64}$")
                sequence_migration = repository.connection.execute(
                    "SELECT migration_sha256 FROM schema_migrations WHERE version = 12"
                ).fetchone()
                self.assertRegex(sequence_migration["migration_sha256"], r"^[0-9a-f]{64}$")
                self.assertEqual(0, repository.count("m4_metric_snapshots"))
            with Repository(path) as repository:
                self.assertEqual(
                    "ok", repository.connection.execute("PRAGMA integrity_check").fetchone()[0]
                )


if __name__ == "__main__":
    unittest.main()
