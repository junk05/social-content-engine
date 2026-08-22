"""Requeue only human-selected detail identities with known date-metadata text."""

import argparse
import json
from typing import Optional, Sequence

from social_content_engine.data.repository import Repository


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    with Repository(args.database) as repository:
        count = repository.requeue_invalid_browser_detail_text()
    print(json.dumps({"requeued_count": count}, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
