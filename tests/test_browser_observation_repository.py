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
    metric_statuses: bool = False,
    approximate_views: dict = None,
    display_views: dict = None,
    views: dict = None,
    topic_tags: list = None,
    timestamp: str = "2026-08-16T00:00:00+00:00",
    published_at_raw: str = None,
    published_at: str = None,
    published_timezone_basis: str = None,
) -> dict:
    surface = "threads_search_card" if observation_type == "SEARCH_CARD" else "threads_post_detail"
    values = {
        "schema_version": 1,
        "observation_type": observation_type,
        "source": "threads",
        "post_url": "https://www.threads.net/@fixture/post/Code123",
        "source_post_id": source_post_id,
        "author_name": "Fixture Author",
        "username": "fixture",
        "text": text,
        "topic_tags": list(topic_tags or []),
        "timestamp": timestamp,
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
    if metric_statuses:
        if observation_type != "POST_DETAIL":
            raise ValueError("metric statuses require a detail fixture")
        values["metric_observation_statuses"] = {
            name: "OBSERVED" if value is not None else "NOT_PRESENT"
            for name, value in values["public_counters"].items()
        }
    if approximate_views is not None:
        values["approximate_views"] = dict(approximate_views)
    if display_views is not None:
        values["display_views"] = dict(display_views)
    if views is not None:
        values["views"] = dict(views)
    if topic_tags:
        values["observed_fields"].append(
            {
                "field": "topic_tags",
                "value": list(topic_tags),
                "surface": surface,
                "observed_at": "2026-08-16T00:00:00+00:00",
                "extractor_version": "fixture-extractor-v1",
            }
        )
    if published_timezone_basis is not None:
        values.update(
            {
                "published_at_raw": published_at_raw,
                "published_at": published_at,
                "published_timezone_basis": published_timezone_basis,
            }
        )
        for field, value in (
            ("published_at_raw", published_at_raw),
            ("published_at", published_at),
            ("published_timezone_basis", published_timezone_basis),
        ):
            if value is not None:
                values["observed_fields"].append(
                    {
                        "field": field,
                        "value": value,
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
        "browser_display_view_observations",
        "browser_approximate_view_observations",
        "browser_metric_observation_statuses",
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
    def test_engagement_display_provenance_preserves_exact_and_rounded_context(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with Repository(Path(directory) / "engagement.sqlite3") as repository:
                payload = observation(observation_type="POST_DETAIL", metric_statuses=True)
                payload["public_counters"].update(
                    {"like_count": 14000, "reply_count": 154, "repost_count": 48}
                )
                payload["metric_observation_statuses"].update(
                    {
                        "like_count": "OBSERVED", "reply_count": "OBSERVED",
                        "repost_count": "OBSERVED",
                    }
                )
                payload["observed_fields"] = [
                    field for field in payload["observed_fields"]
                    if field["field"] != "public_counters.like_count"
                ]
                for name in ("like_count", "reply_count", "repost_count"):
                    payload["observed_fields"].append(
                        {
                            "field": "public_counters." + name,
                            "value": payload["public_counters"][name],
                            "surface": "threads_post_detail",
                            "observed_at": "2026-08-16T00:00:00+00:00",
                            "extractor_version": "fixture-extractor-v1",
                        }
                    )
                payload["engagement_metric_displays"] = {
                    "like_count": {
                        "raw_display": "1.4万", "normalized_value": 14000,
                        "precision": "ROUNDED", "source": "POST_DETAIL_ENGAGEMENT_CONTROL",
                        "observed_at": "2026-08-16T00:00:00+00:00",
                        "extractor_version": "fixture-extractor-v1",
                        "normalizer_version": "engagement-display-normalizer-v1",
                        "relationship_evidence": (
                            "ACTION_ORDER_PRECEDING_REPLY_AND_LOCAL_NUMERIC_DISPLAY"
                        ),
                        "metric_name": "like_count",
                    },
                    "reply_count": {
                        "raw_display": "154", "normalized_value": 154,
                        "precision": "DISPLAY_EXACT", "source": "POST_DETAIL_ENGAGEMENT_CONTROL",
                        "observed_at": "2026-08-16T00:00:00+00:00",
                        "extractor_version": "fixture-extractor-v1",
                        "normalizer_version": "engagement-display-normalizer-v1",
                        "relationship_evidence": "SVG_ARIA_LABEL_AND_LOCAL_NUMERIC_DISPLAY",
                        "metric_name": "reply_count",
                    },
                }
                payload["payload_sha256"] = browser_observation_payload_sha256(payload)
                saved = repository.add_browser_observation(payload)
                normalized = json.loads(
                    repository.connection.execute(
                        """SELECT canonical_payload_json FROM browser_normalized_versions
                        WHERE source_observation_id = ?""",
                        (saved["browser_observation_id"],),
                    ).fetchone()[0]
                )
                self.assertEqual(
                    "ROUNDED", normalized["engagement_metric_displays"]["like_count"]["precision"]
                )
                self.assertEqual(
                    154,
                    normalized["engagement_metric_displays"]["reply_count"]["normalized_value"],
                )

    def test_publication_time_preserves_explicit_offset_without_collection_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with Repository(Path(directory) / "publication-time.sqlite3") as repository:
                payload = observation(
                    observation_type="POST_DETAIL", metric_statuses=True,
                    timestamp="2026-08-16T09:15:00+09:00",
                    published_at_raw="2026-08-16T09:15:00+09:00",
                    published_at="2026-08-16T09:15:00+09:00",
                    published_timezone_basis="TIME_DATETIME_EXPLICIT_OFFSET",
                )
                result = repository.add_browser_observation(payload)
                row = repository.connection.execute(
                    """SELECT canonical_payload_json FROM browser_normalized_versions
                    WHERE browser_post_identity_id = ? ORDER BY version DESC LIMIT 1""",
                    (result["browser_post_identity_id"],),
                ).fetchone()
                normalized = json.loads(str(row["canonical_payload_json"]))
                self.assertEqual("2026-08-16T09:15:00+09:00", normalized["published_at"])
                self.assertEqual(
                    "TIME_DATETIME_EXPLICIT_OFFSET", normalized["published_timezone_basis"]
                )
                self.assertEqual("2026-08-16T09:15:00+09:00", normalized["timestamp"])

    def test_topic_tags_are_separate_versioned_source_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with Repository(Path(directory) / "topics.sqlite3") as repository:
                old_payload = observation(
                    observation_type="POST_DETAIL", text="恋愛", metric_statuses=True
                )
                old = repository.add_browser_observation(old_payload)
                repository.assess_browser_text_quality(
                    browser_observation_id=old["browser_observation_id"],
                    quality_status="VALID_TEXT",
                    input_sha256="0" * 64,
                )
                repaired = observation(
                    observation_type="POST_DETAIL",
                    text="本文です。",
                    metric_statuses=True,
                    topic_tags=["恋愛"],
                )
                repaired["collected_at"] = "2026-08-16T00:01:01+00:00"
                repaired["payload_sha256"] = browser_observation_payload_sha256(repaired)
                saved = repository.add_browser_observation(repaired)
                normalized = json.loads(
                    repository.connection.execute(
                        """SELECT canonical_payload_json FROM browser_normalized_versions
                    WHERE source_observation_id = ?""",
                        (saved["browser_observation_id"],),
                    ).fetchone()[0]
                )
                self.assertEqual("本文です。", normalized["text"])
                self.assertEqual(["恋愛"], normalized["topic_tags"])
                statuses = [
                    row[0]
                    for row in repository.connection.execute(
                        """SELECT quality_status FROM browser_text_quality_assessments
                    WHERE browser_observation_id = ? ORDER BY id""",
                        (old["browser_observation_id"],),
                    )
                ]
                self.assertEqual(["VALID_TEXT", "INVALID_TEXT_TOPIC_TAG_METADATA"], statuses)

                late_old = observation(
                    observation_type="POST_DETAIL",
                    text="夫婦関係",
                    metric_statuses=True,
                )
                late_old["post_url"] = "https://www.threads.net/@fixture/post/Late"
                late_old["payload_sha256"] = browser_observation_payload_sha256(late_old)
                late_old_saved = repository.add_browser_observation(late_old)
                late_new = observation(
                    observation_type="POST_DETAIL",
                    text="別の本文です。",
                    metric_statuses=True,
                    topic_tags=["夫婦関係"],
                )
                late_new["post_url"] = late_old["post_url"]
                late_new["collected_at"] = "2026-08-16T00:02:01+00:00"
                late_new["payload_sha256"] = browser_observation_payload_sha256(late_new)
                repository.add_browser_observation(late_new)
                # Simulate a generic assessor running after the repaired detail.
                self.assertEqual(
                    "INVALID_TEXT_TOPIC_TAG_METADATA",
                    repository.connection.execute(
                        """SELECT quality_status FROM browser_text_quality_assessments
                        WHERE browser_observation_id = ? ORDER BY id DESC LIMIT 1""",
                        (late_old_saved["browser_observation_id"],),
                    ).fetchone()[0],
                )
                self.assertEqual(0, repository.reconcile_browser_topic_tag_text_quality())

                genuine = observation(
                    observation_type="POST_DETAIL",
                    text="恋愛",
                    metric_statuses=True,
                    topic_tags=["恋愛"],
                )
                genuine["post_url"] = "https://www.threads.net/@fixture/post/Genuine"
                genuine["payload_sha256"] = browser_observation_payload_sha256(genuine)
                saved_genuine = repository.add_browser_observation(genuine)
                self.assertEqual(
                    0,
                    repository.connection.execute(
                        """SELECT COUNT(*) FROM browser_text_quality_assessments
                    WHERE browser_observation_id = ?""",
                        (saved_genuine["browser_observation_id"],),
                    ).fetchone()[0],
                )

    def test_schema_and_canonical_url_contract(self) -> None:
        schema = json.loads(
            (ROOT / "spec/contracts/browser-observation.schema.json").read_text(encoding="utf-8")
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

        sequenced = observation(observation_type="POST_DETAIL", metric_statuses=True)
        sequenced.update(
            {
                "raw_sequence_indicator": "1 / 3",
                "thread_position": 1,
                "thread_total": 3,
            }
        )
        for field, value in [
            ("raw_sequence_indicator", "1 / 3"),
            ("thread_position", 1),
            ("thread_total", 3),
        ]:
            sequenced["observed_fields"].append(
                {
                    "field": field,
                    "value": value,
                    "surface": "threads_post_detail",
                    "observed_at": "2026-08-16T00:00:00+00:00",
                    "extractor_version": "fixture-extractor-v1",
                }
            )
        sequenced["payload_sha256"] = browser_observation_payload_sha256(sequenced)
        self.assertEqual([], list(validator.iter_errors(sequenced)))

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

    def test_nullable_detail_metric_statuses_are_validated_and_append_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with Repository(Path(directory) / "metric-status.sqlite3") as repository:
                detail = observation(
                    observation_type="POST_DETAIL", view_count=None, metric_statuses=True
                )
                result = repository.add_browser_observation(detail)
                self.assertEqual("DETAIL_ENRICHED", result["status"])
                rows = repository.connection.execute(
                    """SELECT field_name, observation_status
                    FROM browser_metric_observation_statuses
                    WHERE browser_observation_id = ? ORDER BY field_name""",
                    (result["browser_observation_id"],),
                ).fetchall()
                self.assertEqual(6, len(rows))
                self.assertIn(
                    ("public_counters.view_count", "NOT_PRESENT"),
                    [tuple(row) for row in rows],
                )
                self.assertIn(
                    ("public_counters.like_count", "OBSERVED"),
                    [tuple(row) for row in rows],
                )
                self.assertEqual(6, repository.count("browser_metric_observation_statuses"))
                with self.assertRaisesRegex(sqlite3.IntegrityError, "immutable"):
                    repository.connection.execute(
                        """UPDATE browser_metric_observation_statuses
                        SET observation_status = 'NOT_OBSERVED' WHERE field_name = ?""",
                        ("public_counters.view_count",),
                    )
                repository.connection.rollback()

    def test_metric_status_must_agree_with_nullable_counter(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with Repository(Path(directory) / "metric-validation.sqlite3") as repository:
                invalid = observation(
                    observation_type="POST_DETAIL", view_count=None, metric_statuses=True
                )
                invalid["metric_observation_statuses"]["view_count"] = "OBSERVED"
                invalid["payload_sha256"] = browser_observation_payload_sha256(invalid)
                with self.assertRaisesRegex(ValueError, "value and observation status disagree"):
                    repository.add_browser_observation(invalid)
                invalid = observation(
                    observation_type="POST_DETAIL", view_count=0, metric_statuses=True
                )
                invalid["metric_observation_statuses"]["view_count"] = "NOT_PRESENT"
                invalid["payload_sha256"] = browser_observation_payload_sha256(invalid)
                with self.assertRaisesRegex(ValueError, "value and observation status disagree"):
                    repository.add_browser_observation(invalid)

    def test_rounded_views_are_separate_immutable_source_evidence(self) -> None:
        rounded = {
            "display": "12万",
            "normalized_approx": 120000,
            "precision": "ROUNDED",
            "source": "POST_DETAIL_PAGE",
            "view_band": "100K_1M",
            "observed_at": "2026-08-16T00:00:01+00:00",
            "extractor_version": "fixture-extractor-v1",
            "normalizer_version": "rounded-views-normalizer-v1",
        }
        with tempfile.TemporaryDirectory() as directory:
            with Repository(Path(directory) / "approximate-views.sqlite3") as repository:
                value = observation(
                    observation_type="POST_DETAIL",
                    view_count=None,
                    metric_statuses=True,
                    approximate_views=rounded,
                    views={
                        "raw_display": "12万",
                        "normalized_value": 120000,
                        "precision": "ROUNDED",
                        "display_format": "JAPANESE_MAN",
                        "source": "POST_DETAIL_PAGE",
                        "view_band": "100K_1M",
                        "observed_at": "2026-08-16T00:00:01+00:00",
                        "extractor_version": "fixture-extractor-v1",
                        "normalizer_version": "rounded-views-normalizer-v1",
                    },
                )
                result = repository.add_browser_observation(value)
                row = repository.connection.execute(
                    "SELECT * FROM browser_approximate_view_observations"
                ).fetchone()
                self.assertEqual("12万", row["display"])
                self.assertEqual(120000, row["normalized_approx"])
                self.assertEqual("100K_1M", row["view_band"])
                unified = repository.connection.execute(
                    "SELECT * FROM browser_view_observations"
                ).fetchone()
                self.assertEqual("12万", unified["raw_display"])
                self.assertEqual("JAPANESE_MAN", unified["display_format"])
                self.assertEqual(
                    "browser_approximate_view_observations", unified["legacy_source_table"]
                )
                self.assertIsNone(
                    json.loads(
                        repository.connection.execute(
                            """SELECT canonical_payload_json FROM browser_observations
                        WHERE id = ?""",
                            (result["browser_observation_id"],),
                        ).fetchone()[0]
                    )["public_counters"]["view_count"]
                )
                with self.assertRaisesRegex(sqlite3.IntegrityError, "immutable"):
                    repository.connection.execute(
                        "UPDATE browser_approximate_view_observations SET normalized_approx=1"
                    )
                repository.connection.rollback()

                invalid = observation(
                    observation_type="POST_DETAIL",
                    approximate_views={**rounded, "view_band": "LT_1K"},
                )
                with self.assertRaisesRegex(ValueError, "band disagrees"):
                    repository.add_browser_observation(invalid)

    def test_exact_display_views_are_separate_immutable_source_evidence(self) -> None:
        displayed = {
            "display": "表示4,506回",
            "normalized_value": 4506,
            "precision": "DISPLAY_EXACT",
            "source": "POST_DETAIL_PAGE",
            "view_band": "1K_10K",
            "observed_at": "2026-08-16T00:00:01+00:00",
            "extractor_version": "fixture-extractor-v1",
            "normalizer_version": "display-views-normalizer-v1",
        }
        with tempfile.TemporaryDirectory() as directory:
            with Repository(Path(directory) / "display-views.sqlite3") as repository:
                value = observation(
                    observation_type="POST_DETAIL",
                    metric_statuses=True,
                    display_views=displayed,
                    views={
                        "raw_display": "表示4,506回",
                        "normalized_value": 4506,
                        "precision": "DISPLAY_EXACT",
                        "display_format": "INTEGER",
                        "source": "POST_DETAIL_PAGE",
                        "view_band": "1K_10K",
                        "observed_at": "2026-08-16T00:00:01+00:00",
                        "extractor_version": "fixture-extractor-v1",
                        "normalizer_version": "display-views-normalizer-v1",
                    },
                )
                result = repository.add_browser_observation(value)
                row = repository.connection.execute(
                    "SELECT * FROM browser_display_view_observations"
                ).fetchone()
                self.assertEqual("表示4,506回", row["display"])
                self.assertEqual(4506, row["normalized_value"])
                self.assertEqual("DISPLAY_EXACT", row["precision"])
                unified = repository.connection.execute(
                    "SELECT * FROM browser_view_observations"
                ).fetchone()
                self.assertEqual(4506, unified["normalized_value"])
                self.assertEqual("INTEGER", unified["display_format"])
                self.assertEqual(
                    "browser_display_view_observations", unified["legacy_source_table"]
                )
                self.assertIsNone(
                    json.loads(
                        repository.connection.execute(
                            "SELECT canonical_payload_json FROM browser_observations WHERE id = ?",
                            (result["browser_observation_id"],),
                        ).fetchone()[0]
                    )["public_counters"]["view_count"]
                )
                with self.assertRaisesRegex(sqlite3.IntegrityError, "immutable"):
                    repository.connection.execute(
                        "UPDATE browser_display_view_observations SET normalized_value=1"
                    )
                repository.connection.rollback()

                invalid = observation(
                    observation_type="POST_DETAIL",
                    display_views=displayed,
                    views={
                        "raw_display": "表示4,507回",
                        "normalized_value": 4507,
                        "precision": "DISPLAY_EXACT",
                        "display_format": "INTEGER",
                        "source": "POST_DETAIL_PAGE",
                        "view_band": "1K_10K",
                        "observed_at": "2026-08-16T00:00:01+00:00",
                        "extractor_version": "fixture-extractor-v1",
                        "normalizer_version": "display-views-normalizer-v1",
                    },
                )
                with self.assertRaisesRegex(ValueError, "legacy provenance bridge"):
                    repository.add_browser_observation(invalid)

    def test_views_history_preserves_precision_changes_and_projects_latest(self) -> None:
        exact = {
            "display": "表示4,506回",
            "normalized_value": 4506,
            "precision": "DISPLAY_EXACT",
            "source": "POST_DETAIL_PAGE",
            "view_band": "1K_10K",
            "observed_at": "2026-08-16T00:00:01+00:00",
            "extractor_version": "fixture-extractor-v1",
            "normalizer_version": "display-views-normalizer-v1",
        }
        rounded = {
            "display": "表示1.2万回",
            "normalized_approx": 12000,
            "precision": "ROUNDED",
            "source": "POST_DETAIL_PAGE",
            "view_band": "10K_100K",
            "observed_at": "2026-08-17T00:00:01+00:00",
            "extractor_version": "fixture-extractor-v1",
            "normalizer_version": "rounded-views-normalizer-v1",
        }
        with tempfile.TemporaryDirectory() as directory:
            with Repository(Path(directory) / "views-history.sqlite3") as repository:
                repository.add_browser_observation(observation())
                repository.add_browser_observation(
                    observation(
                        observation_type="POST_DETAIL",
                        display_views=exact,
                        views={
                            "raw_display": exact["display"],
                            "normalized_value": exact["normalized_value"],
                            "precision": exact["precision"],
                            "display_format": "INTEGER",
                            "source": exact["source"],
                            "view_band": exact["view_band"],
                            "observed_at": exact["observed_at"],
                            "extractor_version": exact["extractor_version"],
                            "normalizer_version": exact["normalizer_version"],
                        },
                    )
                )
                repository.add_browser_observation(
                    observation(
                        observation_type="POST_DETAIL",
                        approximate_views=rounded,
                        views={
                            "raw_display": rounded["display"],
                            "normalized_value": rounded["normalized_approx"],
                            "precision": rounded["precision"],
                            "display_format": "JAPANESE_MAN",
                            "source": rounded["source"],
                            "view_band": rounded["view_band"],
                            "observed_at": rounded["observed_at"],
                            "extractor_version": rounded["extractor_version"],
                            "normalizer_version": rounded["normalizer_version"],
                        },
                    )
                )
                history = repository.connection.execute(
                    "SELECT precision, normalized_value FROM browser_view_observations ORDER BY id"
                ).fetchall()
                self.assertEqual(
                    [("DISPLAY_EXACT", 4506), ("ROUNDED", 12000)],
                    [(row["precision"], row["normalized_value"]) for row in history],
                )
                latest = repository.list_collected_browser_roots()[0]
                self.assertEqual("表示1.2万回", latest["views_latest_raw"])
                self.assertEqual("ROUNDED", latest["views_latest_precision"])

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
                self.assertEqual(
                    [], repository.connection.execute("PRAGMA foreign_key_check").fetchall()
                )
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
                self.assertEqual(
                    1,
                    repository.connection.execute(
                        "SELECT COUNT(*) FROM schema_migrations WHERE version = 8"
                    ).fetchone()[0],
                )
            with Repository(path) as repository:
                self.assertEqual(
                    1,
                    repository.connection.execute(
                        "SELECT COUNT(*) FROM schema_migrations WHERE version = 8"
                    ).fetchone()[0],
                )

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
                self.assertEqual(
                    0,
                    connection.execute(
                        "SELECT COUNT(*) FROM schema_migrations WHERE version = 8"
                    ).fetchone()[0],
                )
            finally:
                connection.close()


if __name__ == "__main__":
    unittest.main()
