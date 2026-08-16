"""Minimal M1 Analyzer CLI."""

import argparse
import json
from pathlib import Path
from typing import Optional, Sequence

from social_content_engine.data.repository import Repository

from .mock_adapter import DeterministicMockAdapter
from .orchestrator import analyze_post


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Analyze one normalized public post")
    parser.add_argument("--post-id", required=True)
    parser.add_argument("--source", default="threads", choices=("threads", "threads_browser"))
    parser.add_argument("--database", type=Path, default=Path("data/social_content.sqlite3"))
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--mock",
        action="store_true",
        help="use the deterministic local adapter (the only M1 adapter)",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    with Repository(args.database) as repository:
        result = analyze_post(
            repository,
            args.post_id,
            DeterministicMockAdapter(),
            source=args.source,
            force=args.force,
        )
    print(
        json.dumps(
            {
                "analysis_run_id": result.analysis_run_id,
                "reused": result.reused,
                "payload": result.payload,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
