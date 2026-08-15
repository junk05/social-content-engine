"""Run the minimal local Meta callback HTTP server."""

import argparse
import os
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Sequence

from .service import CallbackConfig, CallbackResponse, MetaCallbackService

MAX_BODY_BYTES = 65_536


class CallbackHandler(BaseHTTPRequestHandler):
    service: MetaCallbackService

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        values = urllib.parse.parse_qs(parsed.query)
        query = {key: items[-1] for key, items in values.items() if items}
        self._send(self.service.handle_get(parsed.path, query))

    def do_POST(self) -> None:
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send(CallbackResponse.json(400, {"error": "invalid_content_length"}))
            return
        if content_length < 1 or content_length > MAX_BODY_BYTES:
            self._send(CallbackResponse.json(413, {"error": "invalid_body_size"}))
            return
        body = self.rfile.read(content_length)
        self._send(
            self.service.handle_post(
                urllib.parse.urlparse(self.path).path,
                body,
                self.headers.get("Content-Type", ""),
            )
        )

    def log_message(self, format_string: str, *args: object) -> None:
        # Deliberately omit paths/query strings to avoid logging OAuth codes.
        print(self.address_string() + " - request completed")

    def _send(self, response: CallbackResponse) -> None:
        self.send_response(response.status)
        self.send_header("Content-Type", response.content_type)
        self.send_header("Content-Length", str(len(response.body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(response.body)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=os.environ.get("META_CALLBACK_HOST", "127.0.0.1"))
    parser.add_argument(
        "--port", type=int, default=int(os.environ.get("META_CALLBACK_PORT", "8787"))
    )
    return parser


def main(argv: Sequence[str] = ()) -> int:
    args = build_parser().parse_args(argv or None)
    config = CallbackConfig(
        app_secret=os.environ.get("THREADS_APP_SECRET", ""),
        oauth_state=os.environ.get("META_OAUTH_STATE", ""),
        public_base_url=os.environ.get("META_PUBLIC_BASE_URL", ""),
    )
    service = MetaCallbackService(config)
    handler = type("ConfiguredCallbackHandler", (CallbackHandler,), {"service": service})
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print("Meta callback server listening on http://" + args.host + ":" + str(args.port))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Meta callback server stopped")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
