"""Requeue known invalid text and explicitly named tag-only audit candidates."""

import argparse
import json
from typing import Optional, Sequence

from social_content_engine.data.repository import Repository


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True)
    parser.add_argument(
        "--topic-candidate", action="append", default=[],
        help="exact legacy text to reobserve; does not mark it invalid by itself",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    with Repository(args.database) as repository:
        invalid_count = repository.requeue_invalid_browser_detail_text()
        candidate_count = repository.requeue_browser_topic_tag_candidates(
            args.topic_candidate
        )
    print(json.dumps({
        "invalid_requeued_count": invalid_count,
        "topic_candidate_requeued_count": candidate_count,
        "requeued_count": invalid_count + candidate_count,
    }, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
