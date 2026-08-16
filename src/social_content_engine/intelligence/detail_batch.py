"""Prepare one completed browser detail batch for existing analysis pipelines."""

import argparse
import json
from typing import Optional, Sequence

from social_content_engine.data.repository import Repository
from social_content_engine.intelligence.clean_dataset import prepare_detail_batch_analysis


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True)
    parser.add_argument("--batch-id", required=True, type=int)
    parser.add_argument("--dataset-key", required=True)
    parser.add_argument("--dataset-version", required=True, type=int)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.batch_id < 1 or args.dataset_version < 1:
        raise SystemExit("batch ID and dataset version must be positive integers")
    with Repository(args.database) as repository:
        result = prepare_detail_batch_analysis(
            repository,
            args.batch_id,
            args.dataset_key,
            args.dataset_version,
        )
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
