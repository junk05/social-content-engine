"""Run the validated loopback Threads browser-ingestion receiver."""

import argparse
import ipaddress
import json
import os
import sqlite3
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence, Set, Type
from urllib.parse import parse_qs, urlsplit

import jsonschema  # type: ignore[import-untyped]

from social_content_engine.data.browser_detail import DETAIL_ATTEMPT_CONTRACT_VERSION
from social_content_engine.data.browser_observation import validate_browser_observation
from social_content_engine.data.repository import Repository

MAX_BODY_BYTES = 65_536
INGEST_PATH = "/browser-ingest/threads"
PENDING_DETAILS_PATH = INGEST_PATH + "/pending-details"
DETAIL_FAILURE_PATH = INGEST_PATH + "/detail-failures"
DEFAULT_PENDING_LIMIT = 50
MAX_PENDING_LIMIT = 100


@dataclass(frozen=True)
class IngestResponse:
    status: int
    payload: Dict[str, Any]
    origin: Optional[str] = None

    @property
    def body(self) -> bytes:
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


class BrowserIngestService:
    def __init__(
        self,
        repository: Repository,
        allowed_origins: Set[str],
        schema: Mapping[str, Any],
    ) -> None:
        if not allowed_origins:
            raise ValueError("at least one extension origin is required")
        self.repository = repository
        self.allowed_origins = frozenset(allowed_origins)
        self.validator = jsonschema.Draft202012Validator(
            schema, format_checker=jsonschema.FormatChecker()
        )

    def handle_options(
        self, path: str, origin: Optional[str], extension_origin: Optional[str] = None
    ) -> IngestResponse:
        request_origin = self._effective_origin(origin, extension_origin)
        error = self._request_error(
            path, request_origin, {INGEST_PATH, PENDING_DETAILS_PATH, DETAIL_FAILURE_PATH}
        )
        return error or IngestResponse(204, {"status": "preflight_ok"}, request_origin)

    def handle_get(
        self, path: str, query: str, origin: Optional[str], extension_origin: Optional[str] = None
    ) -> IngestResponse:
        request_origin = self._effective_origin(origin, extension_origin)
        error = self._request_error(path, request_origin, {PENDING_DETAILS_PATH})
        if error:
            return error
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
        self, path: str, origin: Optional[str], content_type: str, body: bytes
    ) -> IngestResponse:
        error = self._request_error(path, origin, {INGEST_PATH, DETAIL_FAILURE_PATH})
        if error:
            return error
        if content_type.split(";", 1)[0].strip().lower() != "application/json":
            return IngestResponse(415, {"error": "unsupported_media_type"}, origin)
        if not body or len(body) > MAX_BODY_BYTES:
            return IngestResponse(413, {"error": "invalid_body_size"}, origin)
        try:
            decoded = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return IngestResponse(400, {"error": "invalid_json"}, origin)
        if not isinstance(decoded, dict):
            return IngestResponse(422, {"error": "invalid_payload"}, origin)
        if path == DETAIL_FAILURE_PATH:
            return self._handle_detail_failure(decoded, origin)
        if next(self.validator.iter_errors(decoded), None) is not None:
            return IngestResponse(422, {"error": "invalid_observation"}, origin)
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
            return IngestResponse(422, {"error": "invalid_observation"}, origin)
        except sqlite3.DatabaseError:
            return IngestResponse(500, {"error": "persistence_failed"}, origin)
        return IngestResponse(
            201,
            {
                "status": "accepted",
                "observation_id": result["browser_observation_id"],
                "identity_id": result["browser_post_identity_id"],
                "normalized_version": result["browser_normalized_version"],
                "observation_status": result["status"],
            },
            origin,
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
            self.service.handle_post(path, origin, self.headers.get("Content-Type", ""), body)
        )

    def log_message(self, format_string: str, *args: object) -> None:
        # Never log request paths or bodies: both may contain accidental sensitive input.
        print(self.client_address[0] + " - browser ingestion request completed")

    def _send(self, response: IngestResponse) -> None:
        body = b"" if response.status == 204 else response.body
        self.send_response(response.status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if response.origin:
            self.send_header("Access-Control-Allow-Origin", response.origin)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-SCE-Extension-Origin")
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
