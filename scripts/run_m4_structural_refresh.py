#!/usr/bin/env python3
"""Run one local M4 clean structural refresh without exposing source content."""

import argparse
import json
from pathlib import Path

from social_content_engine.data.repository import Repository
from social_content_engine.intelligence.clean_dataset import (
    ROOT_CLEAN_DATASET_VERSION,
    bridge_current_browser_roots,
    create_clean_root_dataset_snapshot,
)
from social_content_engine.intelligence.structural import (
    EXTRACTOR_VERSION,
    TAXONOMY_VERSION,
    derive_structural_features,
    materialize_structural_patterns,
)
from social_content_engine.intelligence.structural_refresh import audit_latest_browser_data
from social_content_engine.intelligence.structural_report import (
    build_structural_pattern_report,
    write_structural_pattern_report,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--dataset-key", default="m4-clean-browser-root-text")
    parser.add_argument("--dataset-version", type=int, required=True)
    parser.add_argument("--comparison-run-id", type=int)
    parser.add_argument("--added-after")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--json-report", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    with Repository(args.database) as repository:
        bridged_roots = bridge_current_browser_roots(repository)
        snapshot = create_clean_root_dataset_snapshot(
            repository, dataset_key=args.dataset_key, version=args.dataset_version
        )
        audit = audit_latest_browser_data(repository, added_after=args.added_after)
        audit.update({
            "bridged_canonical_roots": bridged_roots,
            "clean_snapshot_valid_text_members": snapshot["member_count"],
            "clean_snapshot_invalid_or_unavailable": snapshot["excluded_count"],
            "clean_snapshot_quality_exclusions": snapshot["quality_exclusions"],
        })
        run_id = repository.create_structural_feature_run(
            snapshot["dataset_snapshot_id"], TAXONOMY_VERSION, EXTRACTOR_VERSION,
            {
                "contract_version": ROOT_CLEAN_DATASET_VERSION,
                "source_scope": "CANONICAL_ROOTS_ONLY",
                "thread_relationship_evidence": "DOM_CONTIGUOUS_ROOT_AUTHOR_CHAIN",
                "rounded_views_semantics": "DESCRIPTIVE_ONLY",
            },
        )
        instance_count = derive_structural_features(repository, run_id)
        pattern_count = materialize_structural_patterns(repository, run_id)
        report = build_structural_pattern_report(
            repository, run_id,
            comparison_run_id=args.comparison_run_id,
            data_audit=audit,
        )
        report["execution"] = {
            "structural_instances": instance_count,
            "promoted_patterns": pattern_count,
            "dataset_snapshot_id": snapshot["dataset_snapshot_id"],
            "dataset_key": args.dataset_key,
            "dataset_version": args.dataset_version,
        }
        write_structural_pattern_report(report, args.report)
        args.json_report.parent.mkdir(parents=True, exist_ok=True)
        args.json_report.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(json.dumps({
            "dataset_snapshot_id": snapshot["dataset_snapshot_id"],
            "member_count": snapshot["member_count"],
            "structural_feature_run_id": run_id,
            "pattern_counts": report["pattern_counts"],
            "readiness": report["pattern_library_readiness"],
            "report": str(args.report),
            "json_report": str(args.json_report),
        }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
