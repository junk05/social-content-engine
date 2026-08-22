"""Read-only browser coverage audit and human-review CSV exports."""

import argparse
import csv
import json
import re
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple, cast

_DATE_METADATA = re.compile(r"^\d{4}[/-]\d{1,2}[/-]\d{1,2}$")
_RELATIVE_TIME_METADATA = re.compile(
    r"^(?:\d+\s*(?:分|時間|日|週|ヶ月|か月|月|年|m|min|h|d|w|mo|y)|昨日|一昨日)$",
    re.IGNORECASE,
)

POST_COLUMNS = [
    "canonical_post_id", "collected_at", "author_username", "post_url",
    "source_text", "text_quality", "first_line", "detail_status",
    "detail_attempt_count", "detail_last_error", "rounded_views_raw",
    "rounded_views_normalized", "rounded_views_band", "rounded_views_status",
    "like_count", "reply_count", "repost_count", "quote_count",
    "thread_sequence_observed", "self_reply_count", "extractor_version",
    "first_line_pattern_ids", "post_pattern_ids",
]

THREAD_COLUMNS = [
    "root_canonical_id", "sequence_position", "node_type", "author_username",
    "same_author_as_root", "source_post_id", "reply_to_post_id", "post_url",
    "text", "text_quality", "observed_at", "extractor_version",
    "relationship_eligibility", "exclusion_reason",
]


def connect_read_only(path: Path) -> sqlite3.Connection:
    uri = path.resolve().as_uri() + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    return connection


def _payload(row: Optional[sqlite3.Row]) -> Dict[str, Any]:
    if row is None:
        return {}
    parsed = json.loads(str(row["canonical_payload_json"]))
    return parsed if isinstance(parsed, dict) else {}


def _first_line(text: Any) -> str:
    if not isinstance(text, str):
        return ""
    for raw in text.splitlines() or [text]:
        line = raw.strip()
        if not line or _DATE_METADATA.fullmatch(line) or _RELATIVE_TIME_METADATA.fullmatch(line):
            continue
        match = re.match(r"^.*?[。！？!?]|^.+$", line)
        return match.group(0).strip() if match else line
    return ""


def _root_ids(connection: sqlite3.Connection, since: Optional[str]) -> List[int]:
    query = """SELECT browser_post_identity_id, MIN(collected_at) AS first_collected_at
        FROM browser_observations WHERE observation_type = 'SEARCH_CARD'
        GROUP BY browser_post_identity_id"""
    parameters: Tuple[Any, ...] = ()
    if since is not None:
        query += " HAVING MIN(collected_at) > ?"
        parameters = (since,)
    query += " ORDER BY first_collected_at, browser_post_identity_id"
    return [int(row["browser_post_identity_id"])
            for row in connection.execute(query, parameters)]


def _placeholders(values: Sequence[Any]) -> str:
    return ",".join("?" for _ in values) or "NULL"


def _queue(connection: sqlite3.Connection, identity_id: int) -> Optional[sqlite3.Row]:
    return cast(Optional[sqlite3.Row], connection.execute(
        "SELECT * FROM browser_detail_enrichment_queue WHERE browser_post_identity_id = ?",
        (identity_id,),
    ).fetchone())


def _latest_rounded(connection: sqlite3.Connection, identity_id: int) -> Optional[sqlite3.Row]:
    return cast(Optional[sqlite3.Row], connection.execute(
        """SELECT approximate.* FROM browser_approximate_view_observations approximate
        JOIN browser_observations observation
          ON observation.id = approximate.browser_observation_id
        WHERE observation.browser_post_identity_id = ?
        ORDER BY approximate.id DESC LIMIT 1""",
        (identity_id,),
    ).fetchone())


def _rounded_missing_reason(queue: Optional[sqlite3.Row]) -> str:
    if queue is None or str(queue["status"]) == "DETAIL_PENDING":
        return "DETAIL_NOT_RUN"
    error = str(queue["last_error_code"] or "")
    if error == "PAGE_TIMEOUT":
        return "PAGE_TIMEOUT"
    if error in {"EXTRACTOR_MISMATCH", "INGESTION_FAILED"} or str(
        queue["last_error_type"] or ""
    ) == "EXTRACTION_FAILED":
        return "EXTRACTOR_FAILURE"
    if str(queue["status"]) == "DETAIL_ENRICHED":
        return "VIEWS_NOT_PRESENT"
    if str(queue["status"]) == "DETAIL_FAILED":
        return "OTHER_DETAIL_FAILURE"
    return "OTHER_MISSING"


def _latest_clean_thread_rows(
    connection: sqlite3.Connection, root_id: int
) -> List[sqlite3.Row]:
    detail = connection.execute(
        """SELECT MAX(detail_observation_id) AS detail_observation_id
        FROM browser_thread_sequence_observations
        WHERE root_browser_post_identity_id = ?
          AND relationship_evidence = 'ROOT_DETAIL_PAGE'""",
        (root_id,),
    ).fetchone()
    if detail is None or detail["detail_observation_id"] is None:
        return []
    return connection.execute(
        """SELECT * FROM browser_thread_sequence_observations
        WHERE detail_observation_id = ?
          AND relationship_evidence IN (
            'ROOT_DETAIL_PAGE', 'DOM_CONTIGUOUS_ROOT_AUTHOR_CHAIN'
          )
        ORDER BY sequence_position, id""",
        (int(detail["detail_observation_id"]),),
    ).fetchall()


def audit_browser_coverage(
    connection: sqlite3.Connection, *, since: str
) -> Dict[str, Any]:
    root_ids = _root_ids(connection, since)
    detail: Counter[str] = Counter()
    failures: Counter[str] = Counter()
    rounded: Counter[str] = Counter()
    thread_processed = 0
    thread_observed = 0
    roots_with_self = 0
    self_replies = 0
    clean_nodes = 0
    excluded_pairs: Set[Tuple[int, int]] = set()
    for identity_id in root_ids:
        queue = _queue(connection, identity_id)
        status = str(queue["status"]) if queue is not None else "DETAIL_PENDING"
        detail[status] += 1
        if status == "DETAIL_ENRICHED":
            thread_processed += 1
        if status == "DETAIL_FAILED" and queue is not None:
            failures[str(queue["last_error_code"] or "UNSPECIFIED")] += 1
        approximate = _latest_rounded(connection, identity_id)
        if approximate is not None:
            rounded["OBSERVED"] += 1
        else:
            rounded[_rounded_missing_reason(queue)] += 1
        nodes = _latest_clean_thread_rows(connection, identity_id)
        if nodes:
            thread_observed += 1
            clean_nodes += len(nodes)
            count = sum(int(row["sequence_position"]) > 0 for row in nodes)
            self_replies += count
            roots_with_self += int(count > 0)
        for row in connection.execute(
            """SELECT root_browser_post_identity_id, node_browser_post_identity_id
            FROM browser_thread_sequence_observations
            WHERE root_browser_post_identity_id = ? AND sequence_position > 0
              AND COALESCE(relationship_evidence, '') !=
                  'DOM_CONTIGUOUS_ROOT_AUTHOR_CHAIN'""",
            (identity_id,),
        ):
            excluded_pairs.add((int(row[0]), int(row[1])))
    root_count = len(root_ids)
    rounded_observed = rounded["OBSERVED"]
    rounded_missing = root_count - rounded_observed
    return {
        "cohort": {"collected_after": since, "root_count": root_count},
        "detail_enrichment": {
            "root_count": root_count,
            "DETAIL_ENRICHED": detail["DETAIL_ENRICHED"],
            "DETAIL_FAILED": detail["DETAIL_FAILED"],
            "DETAIL_PENDING": detail["DETAIL_PENDING"],
            "PAGE_TIMEOUT": failures["PAGE_TIMEOUT"],
            "other_failures": {
                key: value for key, value in sorted(failures.items())
                if key != "PAGE_TIMEOUT"
            },
        },
        "rounded_views": {
            "observed": rounded_observed,
            "missing": rounded_missing,
            "coverage_percent": round(100 * rounded_observed / root_count, 1)
            if root_count else 0.0,
            "detail_not_run": rounded["DETAIL_NOT_RUN"],
            "page_timeout": rounded["PAGE_TIMEOUT"],
            "views_not_present": rounded["VIEWS_NOT_PRESENT"],
            "extractor_failure": rounded["EXTRACTOR_FAILURE"],
            "other_missing": rounded["OTHER_DETAIL_FAILURE"] + rounded["OTHER_MISSING"],
        },
        "thread_sequence": {
            "detail_processed_roots": thread_processed,
            "thread_sequence_observed_roots": thread_observed,
            "roots_with_self_replies": roots_with_self,
            "roots_without_self_replies": thread_observed - roots_with_self,
            "relationship_extraction_failures": thread_processed - thread_observed,
            "self_reply_nodes": self_replies,
            "clean_sequence_nodes": clean_nodes,
            "false_positive_or_excluded_nodes": len(excluded_pairs),
        },
    }


def _latest_source_row(
    connection: sqlite3.Connection, identity_id: int
) -> Tuple[Optional[sqlite3.Row], str]:
    row = connection.execute(
        """SELECT observation.*, assessment.quality_status
        FROM browser_observations observation
        LEFT JOIN browser_text_quality_assessments assessment
          ON assessment.browser_observation_id = observation.id
        WHERE observation.browser_post_identity_id = ?
        ORDER BY (assessment.quality_status = 'VALID_TEXT') DESC,
                 observation.collected_at DESC, observation.id DESC LIMIT 1""",
        (identity_id,),
    ).fetchone()
    return row, str(row["quality_status"] or "UNASSESSED") if row is not None else "UNAVAILABLE"


def _latest_counter(
    connection: sqlite3.Connection, identity_id: int, key: str
) -> Any:
    for row in connection.execute(
        """SELECT canonical_payload_json FROM browser_observations
        WHERE browser_post_identity_id = ? ORDER BY collected_at DESC, id DESC""",
        (identity_id,),
    ):
        value = _payload(row).get("public_counters", {}).get(key)
        if value is not None:
            return value
    return None


def _pattern_ids(
    connection: sqlite3.Connection, identity_id: int, kind: str
) -> str:
    row = connection.execute(
        """SELECT MAX(id) AS id FROM structural_feature_runs"""
    ).fetchone()
    if row is None or row["id"] is None:
        return ""
    values = connection.execute(
        """SELECT DISTINCT pattern.id
        FROM structural_patterns pattern
        JOIN structural_pattern_members member
          ON member.structural_pattern_id = pattern.id
        JOIN structural_feature_instances instance
          ON instance.id = member.structural_feature_instance_id
        JOIN browser_normalized_bridges bridge
          ON bridge.normalized_post_version_id = instance.normalized_post_version_id
        WHERE pattern.structural_feature_run_id = ?
          AND pattern.pattern_kind = ?
          AND bridge.browser_post_identity_id = ?
        ORDER BY pattern.id""",
        (int(row["id"]), kind, identity_id),
    ).fetchall()
    return ";".join(str(value["id"]) for value in values)


def _canonical_id(identity: sqlite3.Row) -> str:
    return str(identity["source_post_id"] or identity["post_url"])


def build_post_rows(
    connection: sqlite3.Connection, *, since: Optional[str] = None,
    only_valid_text: bool = False, only_detail_enriched: bool = False,
    only_with_thread: bool = False, sort: str = "collected_at", limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    for identity_id in _root_ids(connection, since):
        identity = connection.execute(
            "SELECT * FROM browser_post_identities WHERE id = ?", (identity_id,)
        ).fetchone()
        source, quality = _latest_source_row(connection, identity_id)
        payload = _payload(source)
        queue = _queue(connection, identity_id)
        detail_status = str(queue["status"]) if queue is not None else "DETAIL_PENDING"
        nodes = _latest_clean_thread_rows(connection, identity_id)
        if only_valid_text and quality != "VALID_TEXT":
            continue
        if only_detail_enriched and detail_status != "DETAIL_ENRICHED":
            continue
        if only_with_thread and not nodes:
            continue
        rounded = _latest_rounded(connection, identity_id)
        text = payload.get("text")
        row = {
            "canonical_post_id": _canonical_id(identity),
            "collected_at": source["collected_at"]
            if source is not None else identity["created_at"],
            "author_username": payload.get("username"),
            "post_url": identity["post_url"],
            "source_text": text,
            "text_quality": quality,
            "first_line": _first_line(text),
            "detail_status": detail_status,
            "detail_attempt_count": int(queue["attempt_count"]) if queue is not None else 0,
            "detail_last_error": queue["last_error_code"] if queue is not None else None,
            "rounded_views_raw": rounded["display"] if rounded is not None else None,
            "rounded_views_normalized": rounded["normalized_approx"]
            if rounded is not None else None,
            "rounded_views_band": rounded["view_band"] if rounded is not None else None,
            "rounded_views_status": "OBSERVED" if rounded is not None
            else _rounded_missing_reason(queue),
            "like_count": _latest_counter(connection, identity_id, "like_count"),
            "reply_count": _latest_counter(connection, identity_id, "reply_count"),
            "repost_count": _latest_counter(connection, identity_id, "repost_count"),
            "quote_count": _latest_counter(connection, identity_id, "quote_count"),
            "thread_sequence_observed": "OBSERVED" if nodes else "NOT_OBSERVED",
            "self_reply_count": sum(int(node["sequence_position"]) > 0 for node in nodes),
            "extractor_version": source["extractor_version"] if source is not None else None,
            "first_line_pattern_ids": _pattern_ids(connection, identity_id, "FIRST_LINE"),
            "post_pattern_ids": _pattern_ids(connection, identity_id, "POST"),
        }
        result.append(row)
    if sort == "views":
        result.sort(key=lambda row: (
            row["rounded_views_normalized"] is None,
            -(int(row["rounded_views_normalized"] or 0)),
            str(row["collected_at"]), str(row["canonical_post_id"]),
        ))
    else:
        result.sort(key=lambda row: (str(row["collected_at"]), str(row["canonical_post_id"])))
    return result[:limit] if limit is not None else result


def _node_source(
    connection: sqlite3.Connection, node_id: int
) -> Tuple[Optional[sqlite3.Row], str, Dict[str, Any]]:
    row = connection.execute(
        """SELECT observation.*, assessment.quality_status
        FROM browser_observations observation
        LEFT JOIN browser_text_quality_assessments assessment
          ON assessment.browser_observation_id = observation.id
        WHERE observation.browser_post_identity_id = ?
        ORDER BY (observation.observation_type = 'POST_DETAIL') DESC,
                 (assessment.quality_status = 'VALID_TEXT') DESC,
                 observation.collected_at DESC, observation.id DESC LIMIT 1""",
        (node_id,),
    ).fetchone()
    quality = str(row["quality_status"] or "UNASSESSED") if row is not None else "UNAVAILABLE"
    return row, quality, _payload(row)


def build_thread_rows(
    connection: sqlite3.Connection, *, since: Optional[str] = None,
    root_limit_ids: Optional[Set[int]] = None,
) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    roots = _root_ids(connection, since)
    if root_limit_ids is not None:
        roots = [root for root in roots if root in root_limit_ids]
    for root_id in roots:
        root_identity = connection.execute(
            "SELECT * FROM browser_post_identities WHERE id = ?", (root_id,)
        ).fetchone()
        eligible = _latest_clean_thread_rows(connection, root_id)
        eligible_ids = {int(row["node_browser_post_identity_id"]) for row in eligible}
        candidates: List[Tuple[sqlite3.Row, str, str]] = [
            (row, "ELIGIBLE", "") for row in eligible
        ]
        excluded = connection.execute(
            """SELECT sequence.* FROM browser_thread_sequence_observations sequence
            JOIN (
              SELECT node_browser_post_identity_id, MAX(id) AS max_id
              FROM browser_thread_sequence_observations
              WHERE root_browser_post_identity_id = ? AND sequence_position > 0
                AND COALESCE(relationship_evidence, '') !=
                    'DOM_CONTIGUOUS_ROOT_AUTHOR_CHAIN'
              GROUP BY node_browser_post_identity_id
            ) latest ON latest.max_id = sequence.id
            ORDER BY sequence.sequence_position, sequence.id""",
            (root_id,),
        ).fetchall()
        candidates.extend(
            (row, "EXCLUDED", "LEGACY_OR_UNOBSERVED_BRANCH_RELATIONSHIP")
            for row in excluded
            if int(row["node_browser_post_identity_id"]) not in eligible_ids
        )
        for node, eligibility, reason in candidates:
            node_id = int(node["node_browser_post_identity_id"])
            identity = connection.execute(
                "SELECT * FROM browser_post_identities WHERE id = ?", (node_id,)
            ).fetchone()
            reply_identity = None
            if node["reply_to_browser_post_identity_id"] is not None:
                reply_identity = connection.execute(
                    "SELECT * FROM browser_post_identities WHERE id = ?",
                    (int(node["reply_to_browser_post_identity_id"]),),
                ).fetchone()
            source, quality, payload = _node_source(connection, node_id)
            result.append({
                "root_canonical_id": _canonical_id(root_identity),
                "sequence_position": int(node["sequence_position"]),
                "node_type": "ROOT" if int(node["sequence_position"]) == 0
                else ("SELF_REPLY" if eligibility == "ELIGIBLE" else "EXCLUDED_NODE"),
                "author_username": payload.get("username"),
                "same_author_as_root": "UNKNOWN" if node["same_author_as_root"] is None
                else int(node["same_author_as_root"]),
                "source_post_id": identity["source_post_id"],
                "reply_to_post_id": _canonical_id(reply_identity)
                if reply_identity is not None else None,
                "post_url": identity["post_url"],
                "text": payload.get("text"),
                "text_quality": quality,
                "observed_at": node["observed_at"],
                "extractor_version": node["extractor_version"],
                "relationship_eligibility": eligibility,
                "exclusion_reason": reason,
            })
    result.sort(key=lambda row: (
        str(row["root_canonical_id"]),
        0 if row["relationship_eligibility"] == "ELIGIBLE" else 1,
        int(row["sequence_position"]), str(row["post_url"]),
    ))
    return result


def _write_csv(path: Path, columns: List[str], rows: Iterable[Dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8-sig", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: "" if value is None else value for key, value in row.items()})
            count += 1
    return count


def export_browser_posts(
    database: Path, output_dir: Path, *, since: Optional[str] = None,
    only_valid_text: bool = False, only_detail_enriched: bool = False,
    only_with_thread: bool = False, sort: str = "collected_at", limit: Optional[int] = None,
) -> Dict[str, Any]:
    with connect_read_only(database) as connection:
        post_rows = build_post_rows(
            connection, since=since, only_valid_text=only_valid_text,
            only_detail_enriched=only_detail_enriched,
            only_with_thread=only_with_thread, sort=sort, limit=limit,
        )
        selected_ids = {
            int(row["id"]) for row in connection.execute(
                "SELECT id, source_post_id, post_url FROM browser_post_identities"
            ) if str(row["source_post_id"] or row["post_url"])
            in {str(item["canonical_post_id"]) for item in post_rows}
        }
        thread_rows = build_thread_rows(connection, since=since, root_limit_ids=selected_ids)
    posts_path = output_dir / "threads_posts.csv"
    nodes_path = output_dir / "threads_thread_nodes.csv"
    return {
        "posts_path": str(posts_path),
        "posts_rows": _write_csv(posts_path, POST_COLUMNS, post_rows),
        "thread_nodes_path": str(nodes_path),
        "thread_nodes_rows": _write_csv(nodes_path, THREAD_COLUMNS, thread_rows),
        "database_modified": False,
    }


def export_main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Export browser evidence for human review")
    parser.add_argument("--database", type=Path, default=Path("data/browser-ingest.sqlite3"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/exports"))
    parser.add_argument("--since")
    parser.add_argument("--sort", choices=("collected_at", "views"), default="collected_at")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--only-valid-text", action="store_true")
    parser.add_argument("--only-detail-enriched", action="store_true")
    parser.add_argument("--only-with-thread", action="store_true")
    args = parser.parse_args(argv)
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be positive")
    result = export_browser_posts(
        args.database, args.output_dir, since=args.since,
        only_valid_text=args.only_valid_text,
        only_detail_enriched=args.only_detail_enriched,
        only_with_thread=args.only_with_thread, sort=args.sort, limit=args.limit,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


def audit_main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Audit a separate browser root cohort")
    parser.add_argument("--database", type=Path, default=Path("data/browser-ingest.sqlite3"))
    parser.add_argument("--since", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    with connect_read_only(args.database) as connection:
        result = audit_browser_coverage(connection, since=args.since)
    rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0
