"""Reproducible M4 refresh over the latest clean browser root observations."""

import json
from typing import Any, Dict, Optional

from social_content_engine.data.repository import Repository


def infer_post_s8_cutoff(repository: Repository) -> Optional[str]:
    """Return the first branch-aware S8 observation time, when available."""
    row = repository.connection.execute(
        """SELECT MIN(observation.collected_at) AS cutoff
        FROM browser_thread_sequence_observations sequence
        JOIN browser_observations observation
          ON observation.id = sequence.detail_observation_id
        WHERE sequence.relationship_evidence =
              'DOM_CONTIGUOUS_ROOT_AUTHOR_CHAIN'
          AND observation.extractor_version LIKE '%v6%'"""
    ).fetchone()
    return str(row["cutoff"]) if row is not None and row["cutoff"] else None


def audit_latest_browser_data(
    repository: Repository, *, added_after: Optional[str] = None
) -> Dict[str, Any]:
    """Return aggregate-only audit evidence; never return text, URL, or author."""
    cutoff = added_after or infer_post_s8_cutoff(repository)
    canonical_roots = int(repository.connection.execute(
        """SELECT COUNT(DISTINCT browser_post_identity_id)
        FROM browser_observations WHERE observation_type = 'SEARCH_CARD'"""
    ).fetchone()[0])
    added_roots = None
    if cutoff is not None:
        added_roots = int(repository.connection.execute(
            """SELECT COUNT(*) FROM (
              SELECT browser_post_identity_id, MIN(collected_at) AS first_collected_at
              FROM browser_observations
              WHERE observation_type = 'SEARCH_CARD'
              GROUP BY browser_post_identity_id
              HAVING MIN(collected_at) > ?
            )""",
            (cutoff,),
        ).fetchone()[0])

    detail_status = {
        str(row["status"]): int(row["count"])
        for row in repository.connection.execute(
            """SELECT identities.status, COUNT(*) AS count
            FROM browser_post_identities identities
            WHERE EXISTS (
              SELECT 1 FROM browser_observations roots
              WHERE roots.browser_post_identity_id = identities.id
                AND roots.observation_type = 'SEARCH_CARD'
            )
            GROUP BY identities.status ORDER BY identities.status"""
        )
    }
    rounded_roots = int(repository.connection.execute(
        """SELECT COUNT(DISTINCT observations.browser_post_identity_id)
        FROM browser_approximate_view_observations approximate
        JOIN browser_observations observations
          ON observations.id = approximate.browser_observation_id
        WHERE EXISTS (
          SELECT 1 FROM browser_observations roots
          WHERE roots.browser_post_identity_id = observations.browser_post_identity_id
            AND roots.observation_type = 'SEARCH_CARD'
        )"""
    ).fetchone()[0])

    clean_sequence_rows = repository.connection.execute(
        """WITH latest AS (
          SELECT root_browser_post_identity_id,
                 MAX(detail_observation_id) AS detail_observation_id
          FROM browser_thread_sequence_observations
          WHERE relationship_evidence = 'DOM_CONTIGUOUS_ROOT_AUTHOR_CHAIN'
          GROUP BY root_browser_post_identity_id
        )
        SELECT latest.root_browser_post_identity_id,
               COUNT(sequence.id) AS node_count,
               SUM(CASE WHEN sequence.sequence_position > 0
                         AND sequence.same_author_as_root = 1
                        THEN 1 ELSE 0 END) AS self_reply_count
        FROM latest
        JOIN browser_thread_sequence_observations sequence
          ON sequence.detail_observation_id = latest.detail_observation_id
         AND sequence.relationship_evidence IN (
           'ROOT_DETAIL_PAGE', 'DOM_CONTIGUOUS_ROOT_AUTHOR_CHAIN'
         )
        GROUP BY latest.root_browser_post_identity_id"""
    ).fetchall()
    thread_roots = len(clean_sequence_rows)
    roots_with_self_reply = sum(int(row["self_reply_count"]) > 0 for row in clean_sequence_rows)
    self_reply_count = sum(int(row["self_reply_count"]) for row in clean_sequence_rows)
    clean_nodes = sum(int(row["node_count"]) for row in clean_sequence_rows)
    excluded_relationships = int(repository.connection.execute(
        """SELECT COUNT(*) FROM browser_thread_sequence_observations
        WHERE sequence_position > 0
          AND COALESCE(relationship_evidence, '') !=
              'DOM_CONTIGUOUS_ROOT_AUTHOR_CHAIN'"""
    ).fetchone()[0])
    duplicate_identity_groups = int(repository.connection.execute(
        """SELECT COUNT(*) FROM (
          SELECT post_url FROM browser_post_identities
          GROUP BY post_url HAVING COUNT(*) > 1
        )"""
    ).fetchone()[0])
    duplicate_observation_replays = int(repository.connection.execute(
        """SELECT COALESCE(SUM(count - 1), 0) FROM (
          SELECT COUNT(*) AS count FROM browser_observations
          GROUP BY browser_post_identity_id, observation_type, payload_sha256
          HAVING COUNT(*) > 1
        )"""
    ).fetchone()[0])
    quality_counts = {
        str(row["quality_status"]): int(row["count"])
        for row in repository.connection.execute(
            """SELECT assessments.quality_status, COUNT(*) AS count
            FROM browser_text_quality_assessments assessments
            JOIN browser_observations observations
              ON observations.id = assessments.browser_observation_id
            WHERE EXISTS (
              SELECT 1 FROM browser_observations roots
              WHERE roots.browser_post_identity_id = observations.browser_post_identity_id
                AND roots.observation_type = 'SEARCH_CARD'
            )
            GROUP BY assessments.quality_status ORDER BY assessments.quality_status"""
        )
    }
    return {
        "added_after": cutoff or "UNAVAILABLE",
        "canonical_root_posts": canonical_roots,
        "new_root_posts_after_s8": added_roots if added_roots is not None else "UNAVAILABLE",
        "root_observation_text_quality_counts": quality_counts,
        "rounded_views_observed_roots": rounded_roots,
        "rounded_views_root_coverage_percent": round(
            100 * rounded_roots / canonical_roots, 1
        ) if canonical_roots else 0.0,
        "detail_enrichment_root_status": detail_status,
        "thread_sequence_observed_roots": thread_roots,
        "roots_with_self_replies": roots_with_self_reply,
        "self_reply_nodes": self_reply_count,
        "clean_thread_sequence_nodes": clean_nodes,
        "excluded_relationship_observations": excluded_relationships,
        "duplicate_identity_groups": duplicate_identity_groups,
        "duplicate_observation_replays": duplicate_observation_replays,
    }


def canonical_audit_json(audit: Dict[str, Any]) -> str:
    return json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
