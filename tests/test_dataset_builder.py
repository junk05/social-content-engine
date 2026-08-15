import tempfile
import unittest
from pathlib import Path

from social_content_engine.data.dataset import build_dataset_snapshot
from social_content_engine.data.repository import Repository
from tests.test_m2_repository import seed_post


class DatasetBuilderTest(unittest.TestCase):
    def test_finalizes_current_versions_in_deterministic_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with Repository(Path(directory) / "test.sqlite3") as repository:
                seed_post(repository)
                result = build_dataset_snapshot(
                    repository,
                    dataset_key="fixture",
                    version=1,
                    created_at="2026-08-16T00:00:00+00:00",
                    finalized_at="2026-08-16T00:01:00+00:00",
                )
                self.assertEqual("FINALIZED", result["status"])
                self.assertEqual(1, result["selected_members"])
                row = repository.connection.execute(
                    """SELECT dataset_members.ordinal, normalized_posts.source_post_id
                    FROM dataset_members
                    JOIN normalized_post_versions
                      ON normalized_post_versions.id = dataset_members.normalized_post_version_id
                    JOIN normalized_posts
                      ON normalized_posts.id = normalized_post_versions.normalized_post_id"""
                ).fetchone()
                self.assertEqual((0, "post-1"), tuple(row))

    def test_bounds_limit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with Repository(Path(directory) / "test.sqlite3") as repository:
                for invalid in (0, 201):
                    with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                        build_dataset_snapshot(
                            repository, dataset_key="fixture", version=1, limit=invalid
                        )


if __name__ == "__main__":
    unittest.main()
