import tempfile
import unittest
from pathlib import Path

from social_content_engine.data.repository import Repository
from social_content_engine.intelligence.structural_refresh import (
    audit_latest_browser_data,
    canonical_audit_json,
)


class StructuralRefreshTest(unittest.TestCase):
    def test_empty_audit_is_aggregate_only_and_missing_is_not_zero(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with Repository(Path(directory) / "test.sqlite3") as repository:
                audit = audit_latest_browser_data(repository)
        self.assertEqual(0, audit["canonical_root_posts"])
        self.assertEqual("UNAVAILABLE", audit["new_root_posts_after_s8"])
        self.assertEqual(0.0, audit["rounded_views_root_coverage_percent"])
        self.assertEqual({}, audit["detail_enrichment_root_status"])
        rendered = canonical_audit_json(audit)
        self.assertNotIn("post_url", rendered)
        self.assertNotIn("username", rendered)
        self.assertNotIn("source_post_id", rendered)


if __name__ == "__main__":
    unittest.main()
