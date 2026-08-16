import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

import jsonschema

from social_content_engine.data.browser_observation import (
    browser_observation_payload_sha256,
    canonical_threads_post_url,
)
from social_content_engine.data.repository import Repository

ROOT = Path(__file__).parents[1]


def observation(
    *,
    observation_type: str = "SEARCH_CARD",
    text: str = "synthetic browser post",
    view_count: int = None,
    source_post_id: str = None,
) -> dict:
    surface = (
        "threads_search_card"
        if observation_type == "SEARCH_CARD"
        else "threads_post_detail"
    )
    values = {
        "schema_version": 1,
        "observation_type": observation_type,
        "source": "threads",
        "post_url": "https://www.threads.net/@fixture/post/Code123",
        "source_post_id": source_post_id,
        "author_name": "Fixture Author",
        "username": "fixture",
        "text": text,
        "timestamp": "2026-08-16T00:00:00+00:00",
        "public_counters": {
            "view_count": view_count,
            "like_count": 0,
            "reply_count": None,
            "repost_count": None,
            "quote_count": None,
            "share_count": None,
        },
        "media_type": "TEXT_POST",
        "has_image": False,
        "has_video": False,
        "collection_context": {
            "surface": surface,
            "page_url": "https://www.threads.net/search?q=fixture",
            "query": "fixture",
            "position": 0,
        },
        "observed_fields": [
            {
                "field": "text",
                "value": text,
                "surface": surface,
                "observed_at": "2026-08-16T00:00:00+00:00",
                "extractor_version": "fixture-extractor-v1",
            },
            {
                "field": "public_counters.like_count",
                "value": 0,
                "surface": surface,
                "observed_at": "2026-08-16T00:00:00+00:00",
                "extractor_version": "fixture-extractor-v1",
            },
        ],
        "collected_at": "2026-08-16T00:00:01+00:00",
        "extractor_version": "fixture-extractor-v1",
    }
    if view_count is not None:
        values["observed_fields"].append(
            {
                "field": "public_counters.view_count",
                "value": view_count,
                "surface": surface,
                "observed_at": "2026-08-16T00:00:00+00:00",
                "extractor_version": "fixture-extractor-v1",
            }
        )
    if source_post_id is not None:
        values["observed_fields"].append(
            {
                "field": "source_post_id",
                "value": source_post_id,
                "surface": surface,
                "observed_at": "2026-08-16T00:00:00+00:00",
                "extractor_version": "fixture-extractor-v1",
            }
        )
    values["payload_sha256"] = browser_observation_payload_sha256(values)
    return values


def downgrade_before_migration_8(path: Path) -> None:
    connection = sqlite3.connect(path)
    for table in (
        "browser_observed_fields",
        "browser_normalized_versions",
        "browser_observations",
        "browser_post_identities",
    ):
        connection.execute("DROP TABLE " + table)
    connection.execute("DELETE FROM schema_migrations WHERE version = 8")
    connection.commit()
    connection.close()


class BrowserObservationRepositoryTest(unittest.TestCase):
    def test_schema_and_canonical_url_contract(self) -> None:
        schema = json.loads(
            (ROOT / "spec/contracts/browser-observation.schema.json").read_text(
                encoding="utf-8"
            )
        )
        validator = jsonschema.Draft202012Validator(
            schema, format_checker=jsonschema.FormatChecker()
        )
        self.assertEqual([], list(validator.iter_errors(observation())))
        self.assertEqual(
            "https://www.threads.net/@fixture/post/Code123",
            canonical_threads_post_url(
                "https://threads.net/@Fixture/post/Code123/?utm_source=test#fragment"
            ),
        )
        invalid = observation()
        invalid["post_url"] += "?query=forbidden"
        invalid["payload_sha256"] = browser_observation_payload_sha256(invalid)
        self.assertTrue(list(validator.iter_errors(invalid)))

    def test_repeated_observations_keep_one_identity_and_reuse_or_version_payload(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with Repository(Path(directory) / "test.sqlite3") as repository:
                first = repository.add_browser_observation(observation())
                second = repository.add_browser_observation(observation())
                changed = repository.add_browser_observation(
                    observation(text="changed visible post")
                )
                self.assertEqual("DETAIL_PENDING", first["status"])
                self.assertTrue(second["normalized_version_reused"])
                self.assertEqual(2, changed["browser_normalized_version"])
                self.assertEqual(1, repository.count("browser_post_identities"))
                self.assertEqual(3, repository.count("browser_observations"))
                self.assertEqual(2, repository.count("browser_normalized_versions"))
                identity = repository.connection.execute(
                    "SELECT * FROM browser_post_identities"
                ).fetchone()
                self.assertEqual("DETAIL_PENDING", identity["status"])

    def test_detail_enrichment_and_nullable_supplemental_source_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with Repository(Path(directory) / "test.sqlite3") as repository:
                repository.add_browser_observation(observation())
                enriched = repository.add_browser_observation(
                    observation(
                        observation_type="POST_DETAIL",
                        view_count=12,
                        source_post_id="supplemental-123",
                    )
                )
                identity = repository.connection.execute(
                    "SELECT source_post_id, status FROM browser_post_identities"
                ).fetchone()
                self.assertEqual("DETAIL_ENRICHED", enriched["status"])
                self.assertEqual(("supplemental-123", "DETAIL_ENRICHED"), tuple(identity))
                repository.add_browser_observation(observation(source_post_id="supplemental-123"))
                current_status = repository.connection.execute(
                    "SELECT status FROM browser_post_identities"
                ).fetchone()[0]
                self.assertEqual("DETAIL_ENRICHED", current_status)
                fields = repository.connection.execute(
                    """SELECT field_name, observed_value_json FROM browser_observed_fields
                    WHERE browser_observation_id = ? ORDER BY field_name""",
                    (enriched["browser_observation_id"],),
                ).fetchall()
                self.assertIn(
                    ("public_counters.view_count", "12"),
                    [(row["field_name"], row["observed_value_json"]) for row in fields],
                )

    def test_hash_mismatch_and_browser_or_credential_leakage_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with Repository(Path(directory) / "test.sqlite3") as repository:
                tampered = observation()
                tampered["payload_sha256"] = "0" * 64
                with self.assertRaisesRegex(ValueError, "hash mismatch"):
                    repository.add_browser_observation(tampered)
                for forbidden in ("raw_dom", "cookie", "access_token"):
                    with self.subTest(forbidden=forbidden):
                        leaked = observation()
                        leaked[forbidden] = "secret-or-page-state"
                        leaked["payload_sha256"] = browser_observation_payload_sha256(leaked)
                        with self.assertRaisesRegex(ValueError, "forbidden"):
                            repository.add_browser_observation(leaked)
                self.assertEqual(0, repository.count("browser_observations"))

    def test_observation_rows_are_immutable_and_database_is_consistent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with Repository(Path(directory) / "test.sqlite3") as repository:
                result = repository.add_browser_observation(observation())
                with self.assertRaisesRegex(sqlite3.IntegrityError, "immutable"):
                    repository.connection.execute(
                        "UPDATE browser_observations SET status = 'COLLECTED' WHERE id = ?",
                        (result["browser_observation_id"],),
                    )
                repository.connection.rollback()
                self.assertEqual([], repository.connection.execute(
                    "PRAGMA foreign_key_check"
                ).fetchall())
                self.assertEqual(
                    "ok", repository.connection.execute("PRAGMA integrity_check").fetchone()[0]
                )

    def test_migration_8_is_additive_idempotent_and_rolls_back_partial_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.sqlite3"
            with Repository(path):
                pass
            downgrade_before_migration_8(path)
            with Repository(path) as repository:
                self.assertEqual(8, repository.connection.execute(
                    "SELECT MAX(version) FROM schema_migrations"
                ).fetchone()[0])
            with Repository(path) as repository:
                self.assertEqual(1, repository.connection.execute(
                    "SELECT COUNT(*) FROM schema_migrations WHERE version = 8"
                ).fetchone()[0])

            conflict = Path(directory) / "conflict.sqlite3"
            with Repository(conflict):
                pass
            downgrade_before_migration_8(conflict)
            connection = sqlite3.connect(conflict)
            connection.execute("CREATE TABLE browser_post_identities (id INTEGER PRIMARY KEY)")
            connection.commit()
            connection.close()
            with self.assertRaises(sqlite3.OperationalError):
                Repository(conflict)
            connection = sqlite3.connect(conflict)
            try:
                self.assertIsNone(
                    connection.execute(
                        "SELECT name FROM sqlite_master WHERE name = 'browser_observations'"
                    ).fetchone()
                )
                self.assertEqual(0, connection.execute(
                    "SELECT COUNT(*) FROM schema_migrations WHERE version = 8"
                ).fetchone()[0])
            finally:
                connection.close()


if __name__ == "__main__":
    unittest.main()
