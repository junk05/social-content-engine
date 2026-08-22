import csv
import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from social_content_engine.data.browser_review_export import (
    audit_browser_coverage,
    connect_read_only,
    export_browser_posts,
    render_browser_review_csv,
)


class BrowserReviewExportTest(unittest.TestCase):
    def test_live_exports_are_git_ignored(self) -> None:
        root = Path(__file__).resolve().parents[1]
        self.assertIn("data/exports/", (root / ".gitignore").read_text(encoding="utf-8"))

    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.database = Path(self.directory.name) / "browser.sqlite3"
        connection = sqlite3.connect(self.database)
        connection.executescript(
            """CREATE TABLE browser_post_identities (
              id INTEGER PRIMARY KEY, post_url TEXT, source_post_id TEXT, status TEXT,
              created_at TEXT, updated_at TEXT
            );
            CREATE TABLE browser_observations (
              id INTEGER PRIMARY KEY, browser_post_identity_id INTEGER,
              observation_type TEXT, canonical_payload_json TEXT, collected_at TEXT,
              extractor_version TEXT, payload_sha256 TEXT
            );
            CREATE TABLE browser_text_quality_assessments (
              id INTEGER PRIMARY KEY, browser_observation_id INTEGER, quality_status TEXT
            );
            CREATE TABLE browser_detail_enrichment_queue (
              id INTEGER PRIMARY KEY, browser_post_identity_id INTEGER, status TEXT,
              attempt_count INTEGER, last_error_code TEXT, last_error_type TEXT,
              enrichment_excluded INTEGER DEFAULT 0
            );
            CREATE TABLE browser_approximate_view_observations (
              id INTEGER PRIMARY KEY, browser_observation_id INTEGER, display TEXT,
              normalized_approx INTEGER, view_band TEXT
            );
            CREATE TABLE browser_thread_sequence_observations (
              id INTEGER PRIMARY KEY, root_browser_post_identity_id INTEGER,
              node_browser_post_identity_id INTEGER,
              reply_to_browser_post_identity_id INTEGER, sequence_position INTEGER,
              same_author_as_root INTEGER, detail_observation_id INTEGER,
              observed_at TEXT, extractor_version TEXT, relationship_evidence TEXT
            );
            CREATE TABLE structural_feature_runs (id INTEGER PRIMARY KEY);
            CREATE TABLE structural_patterns (
              id INTEGER PRIMARY KEY, structural_feature_run_id INTEGER, pattern_kind TEXT
            );
            CREATE TABLE structural_pattern_members (
              structural_pattern_id INTEGER, structural_feature_instance_id INTEGER
            );
            CREATE TABLE structural_feature_instances (
              id INTEGER PRIMARY KEY, normalized_post_version_id INTEGER
            );
            CREATE TABLE browser_normalized_bridges (
              normalized_post_version_id INTEGER, browser_post_identity_id INTEGER
            );"""
        )
        identities = [
            (1, "https://www.threads.com/@a/post/root", "root", "DETAIL_ENRICHED"),
            (2, "https://www.threads.com/@a/post/child", "child", "DETAIL_ENRICHED"),
            (3, "https://www.threads.com/@b/post/pending", "pending", "DETAIL_PENDING"),
            (4, "https://www.threads.com/@a/post/excluded", "excluded", "DETAIL_ENRICHED"),
        ]
        connection.executemany(
            """INSERT INTO browser_post_identities
            VALUES (?, ?, ?, ?, '2026-08-22T12:00:00Z', '2026-08-22T12:00:00Z')""",
            identities,
        )
        def payload(url: str, source_id: str, username: str, text: str, likes: object) -> str:
            return json.dumps({
                "post_url": url, "source_post_id": source_id, "username": username,
                "text": text, "public_counters": {
                    "like_count": likes, "reply_count": 0,
                    "repost_count": None, "quote_count": None,
                },
            }, ensure_ascii=False)
        observations = [
            (1, 1, "SEARCH_CARD", payload(
                identities[0][1], "root", "作者", "日本語の本文です。\n続き", 0
            )),
            (2, 1, "POST_DETAIL", payload(
                identities[0][1], "root", "作者", "日本語の本文です。\n続き", 0
            )),
            (3, 2, "POST_DETAIL", payload(identities[1][1], "child", "作者", "自己返信", 2)),
            (4, 3, "SEARCH_CARD", payload(identities[2][1], "pending", "別作者", "待機中", None)),
            (5, 4, "POST_DETAIL", payload(identities[3][1], "excluded", "作者", "除外返信", 1)),
        ]
        connection.executemany(
            """INSERT INTO browser_observations
            VALUES (?, ?, ?, ?, '2026-08-22T12:00:00Z', 'fixture-v1', 'hash')""",
            observations,
        )
        connection.executemany(
            "INSERT INTO browser_text_quality_assessments VALUES (?, ?, 'VALID_TEXT')",
            [(1, 1), (2, 2), (3, 3), (4, 4), (5, 5)],
        )
        connection.executemany(
            "INSERT INTO browser_detail_enrichment_queue VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(1, 1, "DETAIL_ENRICHED", 1, None, None, 0),
             (2, 3, "DETAIL_PENDING", 0, None, None, 0),
             (3, 4, "DETAIL_ENRICHED", 1, None, None, 1)],
        )
        connection.execute(
            """INSERT INTO browser_approximate_view_observations
            VALUES (1, 2, '1.2万', 12000, '10K_100K')"""
        )
        connection.executemany(
            """INSERT INTO browser_thread_sequence_observations
            VALUES (?, 1, ?, ?, ?, 1, 2, '2026-08-22T12:00:01Z', 'fixture-v6', ?)""",
            [
                (1, 1, None, 0, "ROOT_DETAIL_PAGE"),
                (2, 2, 1, 1, "DOM_CONTIGUOUS_ROOT_AUTHOR_CHAIN"),
                (3, 4, None, 1, None),
            ],
        )
        connection.commit()
        connection.close()

    def tearDown(self) -> None:
        self.directory.cleanup()

    def test_isolated_audit_distinguishes_missing_reasons_and_thread_nodes(self) -> None:
        with connect_read_only(self.database) as connection:
            audit = audit_browser_coverage(
                connection, since="2026-08-22T11:59:59Z"
            )
        self.assertEqual(2, audit["cohort"]["root_count"])
        self.assertEqual(1, audit["detail_enrichment"]["DETAIL_ENRICHED"])
        self.assertEqual(1, audit["detail_enrichment"]["DETAIL_PENDING"])
        self.assertEqual(1, audit["rounded_views"]["observed"])
        self.assertEqual(1, audit["rounded_views"]["detail_not_run"])
        self.assertEqual(50.0, audit["rounded_views"]["coverage_percent"])
        self.assertEqual(1, audit["thread_sequence"]["self_reply_nodes"])
        self.assertEqual(2, audit["thread_sequence"]["clean_sequence_nodes"])
        self.assertEqual(1, audit["thread_sequence"]["false_positive_or_excluded_nodes"])

    def test_csv_is_one_root_per_row_bom_safe_deterministic_and_read_only(self) -> None:
        before = hashlib.sha256(self.database.read_bytes()).hexdigest()
        output = Path(self.directory.name) / "exports"
        first = export_browser_posts(
            self.database, output, since="2026-08-22T11:59:59Z"
        )
        after = hashlib.sha256(self.database.read_bytes()).hexdigest()
        self.assertEqual(before, after)
        self.assertFalse(first["database_modified"])
        self.assertEqual(2, first["posts_rows"])
        self.assertEqual(3, first["thread_nodes_rows"])
        posts_path = Path(first["posts_path"])
        self.assertTrue(posts_path.read_bytes().startswith(b"\xef\xbb\xbf"))
        with posts_path.open(encoding="utf-8-sig", newline="") as source:
            posts = list(csv.DictReader(source))
        self.assertEqual(["pending", "root"], [row["canonical_post_id"] for row in posts])
        root = next(row for row in posts if row["canonical_post_id"] == "root")
        self.assertEqual("日本語の本文です。", root["first_line"])
        self.assertEqual("0", root["like_count"])
        self.assertEqual("", root["repost_count"])
        self.assertEqual("https://www.threads.com/@a/post/root", root["post_url"])
        self.assertEqual("12000", root["rounded_views_normalized"])
        with Path(first["thread_nodes_path"]).open(
            encoding="utf-8-sig", newline=""
        ) as source:
            nodes = list(csv.DictReader(source))
        self.assertEqual(["ROOT", "SELF_REPLY", "EXCLUDED_NODE"],
                         [row["node_type"] for row in nodes])
        self.assertEqual("EXCLUDED", nodes[-1]["relationship_eligibility"])
        second = export_browser_posts(
            self.database, output, since="2026-08-22T11:59:59Z"
        )
        self.assertEqual(first["posts_rows"], second["posts_rows"])

    def test_download_renderer_reuses_rows_filters_and_preserves_database(self) -> None:
        before = hashlib.sha256(self.database.read_bytes()).hexdigest()
        posts, posts_count, posts_name = render_browser_review_csv(
            self.database, export_kind="POSTS", status_filter="DETAIL_ENRICHED"
        )
        threads, thread_count, thread_name = render_browser_review_csv(
            self.database, export_kind="THREAD_NODES", status_filter="DETAIL_ENRICHED"
        )
        after = hashlib.sha256(self.database.read_bytes()).hexdigest()
        self.assertEqual(before, after)
        self.assertEqual("threads_posts.csv", posts_name)
        self.assertEqual("threads_thread_nodes.csv", thread_name)
        self.assertEqual(1, posts_count)
        self.assertEqual(3, thread_count)
        self.assertTrue(posts.startswith(b"\xef\xbb\xbf"))
        self.assertIn("日本語の本文です。", posts.decode("utf-8-sig"))
        self.assertIn("https://www.threads.com/@a/post/root", posts.decode("utf-8-sig"))
        with sqlite3.connect(self.database) as connection:
            connection.execute(
                "UPDATE browser_detail_enrichment_queue SET enrichment_excluded = 1 WHERE id = 1"
            )
        excluded, excluded_count, _ = render_browser_review_csv(
            self.database, export_kind="POSTS", status_filter="EXCLUDED"
        )
        self.assertEqual(1, excluded_count)
        self.assertIn("root", excluded.decode("utf-8-sig"))
        self.assertIn(",EXCLUDED,", excluded.decode("utf-8-sig"))


if __name__ == "__main__":
    unittest.main()
