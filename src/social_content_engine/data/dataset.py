"""Build immutable M2 dataset snapshots from versioned normalized evidence."""

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

from .repository import Repository


def build_dataset_snapshot(
    repository: Repository,
    *,
    dataset_key: str,
    version: int,
    limit: int = 200,
    source: str = "threads",
    created_at: Optional[str] = None,
    finalized_at: Optional[str] = None,
) -> Dict[str, Any]:
    if limit < 1 or limit > 200:
        raise ValueError("dataset limit must be between 1 and 200")
    selection_spec = {
        "selector_version": "m2-current-normalized-v1",
        "source": source,
        "order_by": ["source", "source_post_id"],
        "limit": limit,
        "requires_raw_provenance": True,
    }
    snapshot_id = repository.create_dataset_snapshot(
        dataset_key, version, selection_spec, created_at=created_at
    )
    rows = repository.connection.execute(
        """SELECT normalized_posts.source, normalized_posts.source_post_id,
                  normalized_post_versions.id AS normalized_post_version_id,
                  normalized_post_versions.source_raw_post_id
        FROM normalized_posts
        JOIN normalized_post_versions
          ON normalized_post_versions.id = normalized_posts.current_version_id
        WHERE normalized_posts.source = ?
        ORDER BY normalized_posts.source, normalized_posts.source_post_id
        LIMIT ?""",
        (source, limit),
    ).fetchall()
    selected = 0
    skipped_without_raw = 0
    for row in rows:
        raw_post_id = row["source_raw_post_id"]
        if raw_post_id is None:
            skipped_without_raw += 1
            continue
        repository.add_dataset_member(
            snapshot_id,
            int(row["normalized_post_version_id"]),
            int(raw_post_id),
            selected,
            {
                "selector_version": "m2-current-normalized-v1",
                "reason": "current_version_with_raw_provenance",
            },
        )
        selected += 1
    repository.finalize_dataset_snapshot(snapshot_id, finalized_at=finalized_at)
    snapshot = repository.connection.execute(
        """SELECT selection_spec_sha256, status, finalized_at
        FROM dataset_snapshots WHERE id = ?""",
        (snapshot_id,),
    ).fetchone()
    return {
        "schema_version": 1,
        "dataset_key": dataset_key,
        "dataset_version": version,
        "snapshot_id": snapshot_id,
        "status": snapshot["status"],
        "selection_spec_sha256": snapshot["selection_spec_sha256"],
        "selected_members": selected,
        "skipped_without_raw_provenance": skipped_without_raw,
        "finalized_at": snapshot["finalized_at"],
    }


def build_browser_dataset_snapshot(
    repository: Repository, *, dataset_key: str, version: int, limit: int = 200
) -> Dict[str, Any]:
    """Freeze current browser bridges without pretending they have API raw evidence."""
    snapshot_id = repository.create_dataset_snapshot(
        dataset_key, version, {
            "selector_version": "m3-browser-current-bridge-v1",
            "source": "threads_browser", "limit": limit,
        },
    )
    rows = repository.connection.execute(
        """SELECT browser_normalized_bridges.normalized_post_version_id,
                  browser_normalized_versions.source_observation_id
           FROM browser_normalized_bridges
           JOIN browser_normalized_versions ON browser_normalized_versions.id =
                browser_normalized_bridges.browser_normalized_version_id
           WHERE browser_normalized_bridges.id IN (
             SELECT MAX(id) FROM browser_normalized_bridges GROUP BY browser_post_identity_id
           ) ORDER BY browser_normalized_bridges.browser_post_identity_id LIMIT ?""", (limit,)
    ).fetchall()
    for ordinal, row in enumerate(rows):
        repository.add_browser_dataset_member(snapshot_id, int(row["normalized_post_version_id"]),
                                              int(row["source_observation_id"]), ordinal,
                                              {"reason": "current_browser_bridge"})
    repository.finalize_dataset_snapshot(snapshot_id)
    return {"snapshot_id": snapshot_id, "selected_members": len(rows), "status": "FINALIZED"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=Path("data/social_content.sqlite3"))
    parser.add_argument("--dataset-key", default="m2-live")
    parser.add_argument("--version", type=int, required=True)
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--report", type=Path, default=Path("data/reports/m2-dataset.json"))
    return parser


def main(argv: Sequence[str] = ()) -> int:
    args = build_parser().parse_args(argv or None)
    with Repository(args.database) as repository:
        result = build_dataset_snapshot(
            repository,
            dataset_key=args.dataset_key,
            version=args.version,
            limit=args.limit,
        )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        "Finalized {dataset_key} v{dataset_version}: members={selected_members}; "
        "report={report}".format(report=args.report, **result)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
