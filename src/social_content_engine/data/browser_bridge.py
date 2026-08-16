"""Explicitly bridge one accepted browser post into existing M1/M2 normalized data."""

import argparse
import json
from pathlib import Path
from typing import Sequence

from .repository import Repository


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=Path("data/browser-ingest.sqlite3"))
    parser.add_argument("--post-url", required=True)
    return parser


def main(argv: Sequence[str] = ()) -> int:
    args = build_parser().parse_args(argv or None)
    with Repository(args.database) as repository:
        result = repository.bridge_browser_post(args.post_url)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
