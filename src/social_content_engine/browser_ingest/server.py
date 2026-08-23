"""Run the validated loopback Threads browser-ingestion receiver."""

import argparse
import ipaddress
import json
import os
import sqlite3
import subprocess
import sys
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence, Set, Type
from urllib.parse import parse_qs, urlsplit

import jsonschema  # type: ignore[import-untyped]

from social_content_engine.data.browser_detail import DETAIL_ATTEMPT_CONTRACT_VERSION
from social_content_engine.data.browser_observation import validate_browser_observation
from social_content_engine.data.browser_review_export import (
    render_browser_review_csv_from_connection,
)
from social_content_engine.data.repository import Repository

MAX_BODY_BYTES = 65_536
INGEST_PATH = "/browser-ingest/threads"
PENDING_DETAILS_PATH = INGEST_PATH + "/pending-details"
DETAIL_FAILURE_PATH = INGEST_PATH + "/detail-failures"
THREAD_SEQUENCE_PATH = INGEST_PATH + "/thread-sequences"
DETAIL_QUEUE_SUMMARY_PATH = INGEST_PATH + "/detail-queue/summary"
DETAIL_BATCHES_PATH = INGEST_PATH + "/detail-batches"
DETAIL_QUEUE_CLAIM_PATH = INGEST_PATH + "/detail-queue/claim"
DETAIL_QUEUE_COMPLETE_PATH = INGEST_PATH + "/detail-queue/complete"
DETAIL_QUEUE_FAIL_PATH = INGEST_PATH + "/detail-queue/fail"
COLLECTED_POSTS_PATH = INGEST_PATH + "/collected-posts"
DETAIL_EXCLUSION_PATH = INGEST_PATH + "/detail-exclusion"
METRICS_REENRICH_PATH = INGEST_PATH + "/metrics-reenrich"
REVIEW_EXPORT_PATH = INGEST_PATH + "/review-export"
NATIVE_INPUT_SPIKE_PATH = INGEST_PATH + "/native-input-spike"
NATIVE_INPUT_DIAGNOSTIC_PATH = INGEST_PATH + "/native-input-diagnostic"
NATIVE_INPUT_MOVE_PATH = INGEST_PATH + "/native-input-move"
DEFAULT_PENDING_LIMIT = 50
MAX_PENDING_LIMIT = 100


@dataclass(frozen=True)
class IngestResponse:
    status: int
    payload: Dict[str, Any]
    origin: Optional[str] = None
    raw_body: Optional[bytes] = None
    content_type: str = "application/json"
    content_disposition: Optional[str] = None

    @property
    def body(self) -> bytes:
        if self.raw_body is not None:
            return self.raw_body
        return json.dumps(self.payload, separators=(",", ":"), sort_keys=True).encode("utf-8")


def require_loopback_host(host: str) -> None:
    """Reject configurations that could expose the receiver beyond this machine."""
    try:
        address = ipaddress.ip_address(host)
    except ValueError as error:
        raise ValueError("browser ingestion host must be a loopback IP address") from error
    if not address.is_loopback:
        raise ValueError("browser ingestion host must be a loopback IP address")


def parse_extension_origins(value: str) -> Set[str]:
    origins = {item.strip() for item in value.split(",") if item.strip()}
    for origin in origins:
        parsed = urlsplit(origin)
        extension_id = parsed.hostname or ""
        if (
            parsed.scheme != "chrome-extension"
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or len(extension_id) != 32
            or any(character not in "abcdefghijklmnop" for character in extension_id)
        ):
            raise ValueError("allowed origins must be exact Chrome-extension origins")
    if not origins:
        raise ValueError("at least one Chrome-extension origin is required")
    return origins


def load_schema(path: Optional[Path] = None) -> Dict[str, Any]:
    schema_path = path or (
        Path(__file__).parents[3] / "spec/contracts/browser-observation.schema.json"
    )
    value = json.loads(schema_path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("browser observation schema must be an object")
    return value


def load_thread_sequence_schema() -> Dict[str, Any]:
    path = Path(__file__).parents[3] / "spec/contracts/browser-thread-sequence.schema.json"
    value: Dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return value


class BrowserIngestService:
    def __init__(
        self,
        repository: Repository,
        allowed_origins: Set[str],
        schema: Mapping[str, Any],
        native_click_runner: Optional[Any] = None,
        native_move_runner: Optional[Any] = None,
    ) -> None:
        if not allowed_origins:
            raise ValueError("at least one extension origin is required")
        self.repository = repository
        self.allowed_origins = frozenset(allowed_origins)
        self.validator = jsonschema.Draft202012Validator(
            schema, format_checker=jsonschema.FormatChecker()
        )
        self.thread_sequence_validator = jsonschema.Draft202012Validator(
            load_thread_sequence_schema(), format_checker=jsonschema.FormatChecker()
        )
        self.native_click_runner = native_click_runner or self._run_native_click
        self.native_move_runner = native_move_runner or self._run_native_move
        self.native_click_consumed = False
        self.native_move_consumed = False

    def handle_options(
        self, path: str, origin: Optional[str], extension_origin: Optional[str] = None
    ) -> IngestResponse:
        request_origin = self._effective_origin(origin, extension_origin)
        error = self._request_error(
            path, request_origin,
            {
                INGEST_PATH, PENDING_DETAILS_PATH, DETAIL_FAILURE_PATH,
                THREAD_SEQUENCE_PATH, DETAIL_QUEUE_SUMMARY_PATH, DETAIL_BATCHES_PATH,
                DETAIL_QUEUE_CLAIM_PATH, DETAIL_QUEUE_COMPLETE_PATH,
                DETAIL_QUEUE_FAIL_PATH,
                COLLECTED_POSTS_PATH, DETAIL_EXCLUSION_PATH,
                METRICS_REENRICH_PATH,
                REVIEW_EXPORT_PATH,
                NATIVE_INPUT_SPIKE_PATH,
                NATIVE_INPUT_DIAGNOSTIC_PATH,
                NATIVE_INPUT_MOVE_PATH,
            },
        )
        return error or IngestResponse(204, {"status": "preflight_ok"}, request_origin)

    def handle_get(
        self, path: str, query: str, origin: Optional[str], extension_origin: Optional[str] = None
    ) -> IngestResponse:
        request_origin = self._effective_origin(origin, extension_origin)
        error = self._request_error(
            path, request_origin,
            {
                PENDING_DETAILS_PATH, DETAIL_QUEUE_SUMMARY_PATH,
                COLLECTED_POSTS_PATH, REVIEW_EXPORT_PATH,
            }
        )
        if error:
            return error
        if path == DETAIL_QUEUE_SUMMARY_PATH:
            if query:
                return IngestResponse(400, {"error": "invalid_query"}, request_origin)
            return self._detail_queue_summary(request_origin)
        if path == COLLECTED_POSTS_PATH:
            values = parse_qs(query, keep_blank_values=True)
            if set(values) - {"status", "sort", "limit"} or any(
                len(values.get(key, [])) > 1 for key in ("status", "sort", "limit")
            ):
                return IngestResponse(400, {"error": "invalid_query"}, request_origin)
            status_filter = values.get("status", ["ALL"])[0]
            sort = values.get("sort", ["newest"])[0]
            try:
                limit = int(values.get("limit", ["200"])[0])
                posts = self.repository.list_collected_browser_roots(
                    status_filter=status_filter, sort=sort, limit=limit
                )
            except (TypeError, ValueError, sqlite3.DatabaseError):
                return IngestResponse(400, {"error": "invalid_query"}, request_origin)
            return IngestResponse(
                200, {"status": "ok", "count": len(posts), "posts": list(posts)},
                request_origin,
            )
        if path == REVIEW_EXPORT_PATH:
            values = parse_qs(query, keep_blank_values=True)
            if set(values) != {"kind", "status"} or any(
                len(values.get(key, [])) != 1 for key in ("kind", "status")
            ):
                return IngestResponse(400, {"error": "invalid_query"}, request_origin)
            try:
                rendered, count, filename = render_browser_review_csv_from_connection(
                    self.repository.connection,
                    export_kind=values["kind"][0],
                    status_filter=values["status"][0],
                )
            except (TypeError, ValueError):
                return IngestResponse(400, {"error": "invalid_export"}, request_origin)
            except (OSError, sqlite3.DatabaseError):
                return IngestResponse(500, {"error": "export_failed"}, request_origin)
            return IngestResponse(
                200,
                {"status": "ok", "count": count},
                request_origin,
                raw_body=rendered,
                content_type="text/csv; charset=utf-8",
                content_disposition='attachment; filename="' + filename + '"',
            )
        values = parse_qs(query, keep_blank_values=True)
        if set(values) - {"limit"} or len(values.get("limit", [])) > 1:
            return IngestResponse(400, {"error": "invalid_query"}, request_origin)
        raw_limit = values.get("limit", [str(DEFAULT_PENDING_LIMIT)])[0]
        try:
            limit = int(raw_limit)
        except ValueError:
            return IngestResponse(400, {"error": "invalid_limit"}, request_origin)
        if not 1 <= limit <= MAX_PENDING_LIMIT:
            return IngestResponse(400, {"error": "invalid_limit"}, request_origin)
        urls = self.repository.list_browser_pending_detail_urls(limit=limit)
        return IngestResponse(
            200,
            {"status": "ok", "count": len(urls), "urls": list(urls)},
            request_origin,
        )

    def _effective_origin(
        self, origin: Optional[str], extension_origin: Optional[str]
    ) -> Optional[str]:
        if origin in self.allowed_origins:
            return origin
        if origin in {None, "null"} and extension_origin in self.allowed_origins:
            return extension_origin
        return origin

    def handle_post(
        self,
        path: str,
        origin: Optional[str],
        content_type: str,
        body: bytes,
        extension_origin: Optional[str] = None,
    ) -> IngestResponse:
        request_origin = self._effective_origin(origin, extension_origin)
        error = self._request_error(
            path,
            request_origin,
            {
                INGEST_PATH, DETAIL_FAILURE_PATH, THREAD_SEQUENCE_PATH,
                DETAIL_BATCHES_PATH, DETAIL_QUEUE_CLAIM_PATH,
                DETAIL_QUEUE_COMPLETE_PATH, DETAIL_QUEUE_FAIL_PATH,
                DETAIL_EXCLUSION_PATH,
                METRICS_REENRICH_PATH,
                NATIVE_INPUT_SPIKE_PATH,
                NATIVE_INPUT_DIAGNOSTIC_PATH,
                NATIVE_INPUT_MOVE_PATH,
            },
        )
        if error:
            return error
        if content_type.split(";", 1)[0].strip().lower() != "application/json":
            return IngestResponse(415, {"error": "unsupported_media_type"}, request_origin)
        if not body or len(body) > MAX_BODY_BYTES:
            return IngestResponse(413, {"error": "invalid_body_size"}, request_origin)
        try:
            decoded = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return IngestResponse(400, {"error": "invalid_json"}, request_origin)
        if not isinstance(decoded, dict):
            return IngestResponse(422, {"error": "invalid_payload"}, request_origin)
        if path == DETAIL_BATCHES_PATH:
            return self._handle_detail_batch(decoded, request_origin)
        if path == DETAIL_QUEUE_CLAIM_PATH:
            return self._handle_detail_queue_claim(decoded, request_origin)
        if path == DETAIL_QUEUE_COMPLETE_PATH:
            return self._handle_detail_queue_complete(decoded, request_origin)
        if path == DETAIL_QUEUE_FAIL_PATH:
            return self._handle_detail_queue_fail(decoded, request_origin)
        if path == DETAIL_EXCLUSION_PATH:
            return self._handle_detail_exclusion(decoded, request_origin)
        if path == METRICS_REENRICH_PATH:
            return self._handle_metrics_reenrich(decoded, request_origin)
        if path == DETAIL_FAILURE_PATH:
            return self._handle_detail_failure(decoded, request_origin)
        if path == THREAD_SEQUENCE_PATH:
            return self._handle_thread_sequence(decoded, request_origin)
        if path == NATIVE_INPUT_SPIKE_PATH:
            return self._handle_native_input_spike(decoded, request_origin)
        if path == NATIVE_INPUT_DIAGNOSTIC_PATH:
            return self._handle_native_input_diagnostic(decoded, request_origin)
        if path == NATIVE_INPUT_MOVE_PATH:
            return self._handle_native_input_move(decoded, request_origin)
        if next(self.validator.iter_errors(decoded), None) is not None:
            return IngestResponse(422, {"error": "invalid_observation"}, request_origin)
        try:
            validate_browser_observation(decoded)
            detail_attempt = None
            if decoded["observation_type"] == "POST_DETAIL":
                detail_attempt = {
                    "attempted_at": str(decoded["collected_at"]),
                    "extractor_version": str(decoded["extractor_version"]),
                    "contract_version": DETAIL_ATTEMPT_CONTRACT_VERSION,
                }
            result = self.repository.add_browser_observation(
                decoded, detail_attempt=detail_attempt
            )
        except (ValueError, TypeError):
            return IngestResponse(422, {"error": "invalid_observation"}, request_origin)
        except sqlite3.DatabaseError:
            return IngestResponse(500, {"error": "persistence_failed"}, request_origin)
        return IngestResponse(
            201,
            {
                "status": "accepted",
                "observation_id": result["browser_observation_id"],
                "identity_id": result["browser_post_identity_id"],
                "normalized_version": result["browser_normalized_version"],
                "observation_status": result["status"],
            },
            request_origin,
        )

    def _detail_queue_summary(self, origin: Optional[str]) -> IngestResponse:
        counts = {
            "DETAIL_PENDING": 0,
            "DETAIL_PROCESSING": 0,
            "DETAIL_ENRICHED": 0,
            "DETAIL_FAILED": 0,
        }
        for row in self.repository.connection.execute(
            "SELECT status, COUNT(*) AS count FROM browser_detail_enrichment_queue "
            "GROUP BY status"
        ).fetchall():
            counts[str(row["status"])] = int(row["count"])
        excluded = self.repository.connection.execute(
            """SELECT COUNT(*) AS count FROM browser_detail_enrichment_queue
            WHERE enrichment_excluded = 1"""
        ).fetchone()
        total = self.repository.connection.execute(
            "SELECT COUNT(*) AS count FROM browser_post_identities"
        ).fetchone()
        running = self.repository.connection.execute(
            """SELECT id FROM browser_detail_enrichment_batches
            WHERE status = 'RUNNING' ORDER BY id DESC LIMIT 1"""
        ).fetchone()
        return IngestResponse(
            200,
            {
                "status": "ok",
                "collected_count": int(total["count"]) if total else 0,
                "counts": counts,
                "excluded_count": int(excluded["count"]) if excluded else 0,
                "running_batch_id": None if running is None else int(running["id"]),
            },
            origin,
        )

    @staticmethod
    def _native_coordinate(value: Any) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("invalid coordinate")
        coordinate = float(value)
        if not -10000 <= coordinate <= 10000:
            raise ValueError("invalid coordinate")
        return coordinate

    @staticmethod
    def _run_native_click(x: float, y: float) -> str:
        helper = Path(__file__).parents[3] / "scripts" / "macos_native_click.swift"
        if sys.platform != "darwin" or not helper.is_file():
            return "unavailable"
        completed = subprocess.run(
            ["/usr/bin/swift", str(helper), str(x), str(y)],
            capture_output=True, text=True, timeout=10, check=False,
        )
        codes = {
            0: "clicked",
            64: "coordinate_out_of_bounds",
            70: "cgevent_create_failed",
            77: "accessibility_permission_required",
        }
        return codes.get(completed.returncode, "helper_runtime_error")

    @staticmethod
    def _run_native_move(x: float, y: float) -> str:
        helper = Path(__file__).parents[3] / "scripts" / "macos_native_click.swift"
        if sys.platform != "darwin" or not helper.is_file():
            return "unavailable"
        completed = subprocess.run(
            ["/usr/bin/swift", str(helper), "--move", str(x), str(y)],
            capture_output=True, text=True, timeout=10, check=False,
        )
        codes = {
            0: "cursor_moved", 64: "coordinate_out_of_bounds",
            65: "coordinate_out_of_display_bounds", 71: "cursor_move_failed",
            72: "cursor_position_mismatch", 77: "accessibility_permission_required",
        }
        return codes.get(completed.returncode, "helper_runtime_error")

    def _handle_native_input_move(
        self, decoded: Dict[str, Any], origin: Optional[str]
    ) -> IngestResponse:
        if (
            self.native_move_consumed
            or set(decoded) != {"action", "x", "y"}
            or decoded.get("action") != "move_cursor"
        ):
            return IngestResponse(422, {"status": "unavailable"}, origin)
        try:
            x = self._native_coordinate(decoded["x"])
            y = self._native_coordinate(decoded["y"])
        except (KeyError, TypeError, ValueError):
            return IngestResponse(422, {"status": "unavailable"}, origin)
        self.native_move_consumed = True
        try:
            status = self.native_move_runner(x, y)
        except (OSError, subprocess.SubprocessError):
            status = "helper_runtime_error"
        return IngestResponse(200, {"status": status}, origin)

    def _handle_native_input_spike(
        self, decoded: Dict[str, Any], origin: Optional[str]
    ) -> IngestResponse:
        if self.native_click_consumed or set(decoded) != {"x", "y"}:
            return IngestResponse(422, {"status": "unavailable"}, origin)
        try:
            x = self._native_coordinate(decoded["x"])
            y = self._native_coordinate(decoded["y"])
        except (KeyError, TypeError, ValueError):
            return IngestResponse(422, {"status": "unavailable"}, origin)
        self.native_click_consumed = True
        try:
            status = self.native_click_runner(x, y)
        except (OSError, subprocess.SubprocessError):
            status = "failed"
        allowed_statuses = {
            "clicked",
            "accessibility_permission_required",
            "unavailable",
            "coordinate_out_of_bounds",
            "cgevent_create_failed",
            "helper_runtime_error",
        }
        if status not in allowed_statuses:
            status = "helper_runtime_error"
        return IngestResponse(200, {"status": status}, origin)

    @staticmethod
    def _run_native_diagnostic() -> str:
        helper = Path(__file__).parents[3] / "scripts" / "macos_native_click.swift"
        if sys.platform != "darwin" or not helper.is_file():
            return "helper_unavailable"
        completed = subprocess.run(
            ["/usr/bin/swift", str(helper), "--diagnose"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        if completed.returncode == 0:
            return "accessibility_allowed"
        if completed.returncode == 77:
            return "accessibility_permission_required"
        return "helper_launch_failed"

    def _handle_native_input_diagnostic(
        self, decoded: Dict[str, Any], origin: Optional[str]
    ) -> IngestResponse:
        if decoded != {"action": "diagnose"}:
            return IngestResponse(422, {"status": "invalid_diagnostic"}, origin)
        try:
            status = self._run_native_diagnostic()
        except (OSError, subprocess.SubprocessError):
            status = "helper_launch_failed"
        return IngestResponse(200, {"status": status}, origin)

    def _handle_detail_batch(
        self, decoded: Dict[str, Any], origin: Optional[str]
    ) -> IngestResponse:
        action = decoded.get("action")
        try:
            if action == "start" and set(decoded) == {
                "action", "requested_items", "max_items", "retry_failed",
            }:
                requested = decoded["requested_items"]
                maximum = decoded["max_items"]
                retry_failed = decoded["retry_failed"]
                if (
                    isinstance(requested, bool) or not isinstance(requested, int)
                    or isinstance(maximum, bool) or not isinstance(maximum, int)
                    or not 1 <= requested <= maximum <= MAX_PENDING_LIMIT
                    or not isinstance(retry_failed, bool)
                ):
                    raise ValueError("invalid batch bounds")
                if retry_failed:
                    failed = self.repository.connection.execute(
                        """SELECT browser_post_identities.post_url
                        FROM browser_detail_enrichment_queue
                        JOIN browser_post_identities ON browser_post_identities.id =
                          browser_detail_enrichment_queue.browser_post_identity_id
                        WHERE browser_detail_enrichment_queue.status = 'DETAIL_FAILED'
                          AND browser_detail_enrichment_queue.enrichment_excluded = 0
                        ORDER BY browser_detail_enrichment_queue.id LIMIT ?""",
                        (requested,),
                    ).fetchall()
                    for row in failed:
                        self.repository.enqueue_browser_detail(str(row["post_url"]))
                batch_id = self.repository.start_browser_detail_batch(
                    requested_items=requested, max_items=maximum
                )
                summary = self.repository.browser_detail_batch_summary(batch_id)
            elif action == "resume" and set(decoded) == {"action", "batch_id"}:
                batch_id = self._positive_int(decoded["batch_id"])
                summary = self.repository.resume_browser_detail_batch(batch_id)
            elif action == "finish" and set(decoded) == {"action", "batch_id", "stopped"}:
                batch_id = self._positive_int(decoded["batch_id"])
                if not isinstance(decoded["stopped"], bool):
                    raise ValueError("invalid stopped flag")
                summary = self.repository.finish_browser_detail_batch(
                    batch_id, stopped=decoded["stopped"]
                )
            else:
                raise ValueError("invalid batch action")
        except (KeyError, TypeError, ValueError, sqlite3.DatabaseError):
            return IngestResponse(422, {"error": "invalid_detail_batch"}, origin)
        return IngestResponse(
            200,
            {
                "status": "accepted",
                "batch_id": int(summary["id"]),
                "batch_status": str(summary["status"]),
                "assigned_items": int(summary["assigned_items"]),
                "counts": summary["counts"],
            },
            origin,
        )

    def _handle_detail_exclusion(
        self, decoded: Dict[str, Any], origin: Optional[str]
    ) -> IngestResponse:
        if set(decoded) != {"action", "post_url"}:
            return IngestResponse(422, {"error": "invalid_detail_exclusion"}, origin)
        action = decoded.get("action")
        post_url = decoded.get("post_url")
        if action not in {"EXCLUDE", "REQUEUE"} or not isinstance(post_url, str):
            return IngestResponse(422, {"error": "invalid_detail_exclusion"}, origin)
        try:
            result = (
                self.repository.exclude_browser_detail_enrichment(post_url)
                if action == "EXCLUDE"
                else self.repository.requeue_browser_detail_enrichment(post_url)
            )
        except (KeyError, TypeError, ValueError, sqlite3.DatabaseError):
            return IngestResponse(422, {"error": "invalid_detail_exclusion"}, origin)
        return IngestResponse(
            200,
            {
                "status": "accepted",
                "changed": bool(result["changed"]),
                "enrichment_excluded": bool(result["excluded"]),
            },
            origin,
        )

    def _handle_metrics_reenrich(
        self, decoded: Dict[str, Any], origin: Optional[str]
    ) -> IngestResponse:
        if decoded:
            return IngestResponse(422, {"error": "invalid_metrics_reenrich"}, origin)
        try:
            result = self.repository.requeue_missing_browser_engagement_metrics()
        except (TypeError, ValueError, sqlite3.DatabaseError):
            return IngestResponse(422, {"error": "invalid_metrics_reenrich"}, origin)
        return IngestResponse(
            200,
            {"status": "accepted", "count": int(result["count"]),
             "missing_by_metric": result["missing_by_metric"]},
            origin,
        )

    def _handle_detail_queue_claim(
        self, decoded: Dict[str, Any], origin: Optional[str]
    ) -> IngestResponse:
        if set(decoded) != {"batch_id"}:
            return IngestResponse(422, {"error": "invalid_detail_claim"}, origin)
        try:
            batch_id = self._positive_int(decoded["batch_id"])
            claim = self.repository.claim_browser_detail(batch_id)
        except (KeyError, TypeError, ValueError, sqlite3.DatabaseError):
            return IngestResponse(422, {"error": "invalid_detail_claim"}, origin)
        if claim is None:
            return IngestResponse(200, {"status": "empty", "batch_id": batch_id}, origin)
        return IngestResponse(
            200,
            {
                "status": "claimed",
                "queue_item_id": int(claim["queue_item_id"]),
                "batch_id": int(claim["batch_id"]),
                "attempt": int(claim["attempt"]),
                "lease_version": int(claim["lease_version"]),
                "post_url": str(claim["post_url"]),
            },
            origin,
        )

    def _handle_detail_queue_complete(
        self, decoded: Dict[str, Any], origin: Optional[str]
    ) -> IngestResponse:
        required = {
            "queue_item_id", "batch_id", "attempt", "lease_version",
            "detail_observation_id",
        }
        if set(decoded) != required:
            return IngestResponse(422, {"error": "invalid_detail_completion"}, origin)
        try:
            values = {key: self._positive_int(decoded[key]) for key in required}
            self.repository.complete_browser_detail_queue(
                values["queue_item_id"], batch_id=values["batch_id"],
                attempt=values["attempt"], lease_version=values["lease_version"],
                detail_observation_id=values["detail_observation_id"],
            )
        except (KeyError, TypeError, ValueError, sqlite3.DatabaseError):
            return IngestResponse(422, {"error": "invalid_detail_completion"}, origin)
        return IngestResponse(200, {"status": "completed"}, origin)

    def _handle_detail_queue_fail(
        self, decoded: Dict[str, Any], origin: Optional[str]
    ) -> IngestResponse:
        required = {
            "queue_item_id", "batch_id", "attempt", "lease_version",
            "attempted_at", "extractor_version", "contract_version",
            "failure_type", "failure_reason", "error_code",
        }
        if set(decoded) != required:
            return IngestResponse(422, {"error": "invalid_detail_queue_failure"}, origin)
        try:
            attempt_id = self.repository.fail_browser_detail_queue(
                self._positive_int(decoded["queue_item_id"]),
                batch_id=self._positive_int(decoded["batch_id"]),
                attempt=self._positive_int(decoded["attempt"]),
                lease_version=self._positive_int(decoded["lease_version"]),
                attempted_at=self._string(decoded["attempted_at"]),
                extractor_version=self._string(decoded["extractor_version"]),
                contract_version=self._string(decoded["contract_version"]),
                failure_type=self._string(decoded["failure_type"]),
                failure_reason=self._string(decoded["failure_reason"]),
                error_code=self._string(decoded["error_code"]),
            )
        except (KeyError, TypeError, ValueError, sqlite3.DatabaseError):
            return IngestResponse(422, {"error": "invalid_detail_queue_failure"}, origin)
        return IngestResponse(
            201, {"status": "failure_recorded", "attempt_id": attempt_id}, origin
        )

    @staticmethod
    def _positive_int(value: Any) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError("value must be a positive integer")
        return int(value)

    @staticmethod
    def _string(value: Any) -> str:
        if not isinstance(value, str):
            raise ValueError("value must be a string")
        return value

    def _handle_thread_sequence(
        self, decoded: Dict[str, Any], origin: Optional[str]
    ) -> IngestResponse:
        if next(self.thread_sequence_validator.iter_errors(decoded), None) is not None:
            return IngestResponse(422, {"error": "invalid_thread_sequence"}, origin)
        try:
            root = self.repository.connection.execute(
                "SELECT id FROM browser_post_identities WHERE post_url = ?",
                (decoded["root_post_url"],),
            ).fetchone()
            if root is None:
                raise ValueError("unknown root")
            entries = []
            for node in decoded["nodes"]:
                identity = self.repository.connection.execute(
                    "SELECT id FROM browser_post_identities WHERE post_url = ?", (node["post_url"],)
                ).fetchone()
                parent = None
                if node["reply_to_post_url"] is not None:
                    parent = self.repository.connection.execute(
                        "SELECT id FROM browser_post_identities WHERE post_url = ?",
                        (node["reply_to_post_url"],),
                    ).fetchone()
                if identity is None or (node["reply_to_post_url"] is not None and parent is None):
                    raise ValueError("unknown node")
                entries.append({
                    "node_identity_id": int(identity["id"]),
                    "reply_to_identity_id": None if parent is None else int(parent["id"]),
                    "sequence_position": int(node["sequence_position"]),
                    "same_author_as_root": node["same_author_as_root"],
                    "relationship_evidence": node["relationship_evidence"],
                    "observed_at": str(decoded["observed_at"]),
                })
            self.repository.record_browser_thread_sequence_observations(
                root_identity_id=int(root["id"]),
                detail_observation_id=int(decoded["detail_observation_id"]),
                extractor_version=str(decoded["extractor_version"]), entries=entries,
            )
            assessment = self.repository.assess_browser_thread_extraction(
                root_identity_id=int(root["id"]),
                detail_observation_id=int(decoded["detail_observation_id"]),
                extractor_version=str(decoded["extractor_version"]),
                diagnostic=decoded["thread_extraction"],
                assessed_at=str(decoded["observed_at"]),
            )
            count = len(entries)
        except (TypeError, ValueError, sqlite3.DatabaseError):
            return IngestResponse(422, {"error": "invalid_thread_sequence"}, origin)
        return IngestResponse(
            201,
            {"status": "accepted", "node_count": count,
             "thread_extraction_status": assessment["assessment_status"]}, origin,
        )

    def _handle_detail_failure(
        self, decoded: Dict[str, Any], origin: Optional[str]
    ) -> IngestResponse:
        required = {
            "post_url",
            "attempted_at",
            "extractor_version",
            "contract_version",
            "failure_type",
            "failure_reason",
        }
        if set(decoded) != required or any(
            not isinstance(decoded[key], str) for key in required
        ):
            return IngestResponse(422, {"error": "invalid_detail_failure"}, origin)
        try:
            attempt_id = self.repository.record_browser_detail_failure(
                post_url=decoded["post_url"],
                attempted_at=decoded["attempted_at"],
                extractor_version=decoded["extractor_version"],
                contract_version=decoded["contract_version"],
                failure_type=decoded["failure_type"],
                failure_reason=decoded["failure_reason"],
            )
        except (KeyError, TypeError, ValueError):
            return IngestResponse(422, {"error": "invalid_detail_failure"}, origin)
        return IngestResponse(
            201, {"status": "failure_recorded", "attempt_id": attempt_id}, origin
        )

    def _request_error(
        self, path: str, origin: Optional[str], allowed_paths: Set[str]
    ) -> Optional[IngestResponse]:
        if path not in allowed_paths:
            return IngestResponse(404, {"error": "not_found"})
        if origin not in self.allowed_origins:
            return IngestResponse(403, {"error": "origin_not_allowed"})
        return None


class BrowserIngestHandler(BaseHTTPRequestHandler):
    service: BrowserIngestService

    def do_OPTIONS(self) -> None:
        self._send(
            self.service.handle_options(
                urlsplit(self.path).path,
                self.headers.get("Origin"),
                self.headers.get("X-SCE-Extension-Origin"),
            )
        )

    def do_GET(self) -> None:
        parsed = urlsplit(self.path)
        self._send(
            self.service.handle_get(
                parsed.path,
                parsed.query,
                self.headers.get("Origin"),
                self.headers.get("X-SCE-Extension-Origin"),
            )
        )

    def do_POST(self) -> None:
        origin = self.headers.get("Origin")
        path = urlsplit(self.path).path
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send(IngestResponse(400, {"error": "invalid_content_length"}, origin))
            return
        if length < 1 or length > MAX_BODY_BYTES:
            self._send(IngestResponse(413, {"error": "invalid_body_size"}, origin))
            return
        body = self.rfile.read(length)
        self._send(
            self.service.handle_post(
                path,
                origin,
                self.headers.get("Content-Type", ""),
                body,
                self.headers.get("X-SCE-Extension-Origin"),
            )
        )

    def log_message(self, format_string: str, *args: object) -> None:
        # Never log request paths or bodies: both may contain accidental sensitive input.
        print(self.client_address[0] + " - browser ingestion request completed")

    def _send(self, response: IngestResponse) -> None:
        body = b"" if response.status == 204 else response.body
        self.send_response(response.status)
        self.send_header("Content-Type", response.content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if response.content_disposition:
            self.send_header("Content-Disposition", response.content_disposition)
        if response.origin:
            self.send_header("Access-Control-Allow-Origin", response.origin)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-SCE-Extension-Origin")
            self.send_header("Access-Control-Expose-Headers", "Content-Disposition")
        self.end_headers()
        if body:
            self.wfile.write(body)


def configured_handler(service: BrowserIngestService) -> Type[BrowserIngestHandler]:
    return type("ConfiguredBrowserIngestHandler", (BrowserIngestHandler,), {"service": service})


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=os.environ.get("SCE_BROWSER_INGEST_HOST", "127.0.0.1"))
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("SCE_BROWSER_INGEST_PORT", "8765")),
    )
    parser.add_argument("--database", type=Path, default=Path("data/browser-ingest.sqlite3"))
    parser.add_argument(
        "--allowed-origins",
        default=os.environ.get("SCE_BROWSER_EXTENSION_ORIGINS", ""),
    )
    return parser


def main(argv: Sequence[str] = ()) -> int:
    args = build_parser().parse_args(argv or None)
    require_loopback_host(args.host)
    origins = parse_extension_origins(args.allowed_origins)
    with Repository(args.database) as repository:
        service = BrowserIngestService(repository, origins, load_schema())
        # A single-threaded loop also keeps the SQLite connection on its creating thread.
        server = HTTPServer((args.host, args.port), configured_handler(service))
        print("Browser ingestion receiver listening on loopback port " + str(args.port))
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("Browser ingestion receiver stopped")
        finally:
            server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
