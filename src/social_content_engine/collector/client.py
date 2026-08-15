"""Low-volume Threads API client for the explicit M0 spike."""

import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Mapping, cast

BASE_URL = "https://graph.threads.net"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass(frozen=True)
class HttpCapture:
    endpoint: str
    request_params: Dict[str, str]
    started_at: str
    completed_at: str
    status: int
    headers: Dict[str, str]
    body: bytes


class ThreadsClient:
    def __init__(self, access_token: str, timeout: int = 30, max_retries: int = 2) -> None:
        if not access_token:
            raise ValueError("A non-empty Threads access token is required")
        self.access_token = access_token
        self.timeout = timeout
        self.max_retries = max_retries

    def keyword_search(
        self,
        *,
        query: str,
        search_type: str,
        fields: str,
        limit: int,
        after: str = "",
    ) -> HttpCapture:
        if search_type not in {"TOP", "RECENT"}:
            raise ValueError("search_type must be TOP or RECENT")
        params = {
            "q": query,
            "search_type": search_type,
            "fields": fields,
            "limit": str(limit),
        }
        if after:
            params["after"] = after
        return self._get("/keyword_search", params)

    def _get(self, endpoint: str, params: Mapping[str, str]) -> HttpCapture:
        persisted_params = dict(params)
        request_params = dict(params)
        request_params["access_token"] = self.access_token
        url = BASE_URL + endpoint + "?" + urllib.parse.urlencode(request_params)
        started_at = utc_now()
        last_error: urllib.error.HTTPError
        for attempt in range(self.max_retries + 1):
            try:
                request = urllib.request.Request(url, headers={"Accept": "application/json"})
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    body = response.read()
                    return HttpCapture(
                        endpoint=endpoint,
                        request_params=persisted_params,
                        started_at=started_at,
                        completed_at=utc_now(),
                        status=int(response.status),
                        headers=_safe_headers(cast(Mapping[str, str], response.headers)),
                        body=body,
                    )
            except urllib.error.HTTPError as error:
                last_error = error
                body = error.read()
                if error.code not in {429, 500, 502, 503, 504} or attempt >= self.max_retries:
                    return HttpCapture(
                        endpoint=endpoint,
                        request_params=persisted_params,
                        started_at=started_at,
                        completed_at=utc_now(),
                        status=int(error.code),
                        headers=_safe_headers(cast(Mapping[str, str], error.headers)),
                        body=body,
                    )
                retry_after = error.headers.get("Retry-After", "1")
                try:
                    delay = min(max(int(retry_after), 1), 30)
                except ValueError:
                    delay = 1
                time.sleep(delay)
        raise last_error


def _safe_headers(headers: Mapping[str, str]) -> Dict[str, str]:
    allowed = {
        "content-type",
        "date",
        "etag",
        "retry-after",
        "x-app-usage",
        "x-business-use-case-usage",
        "x-fb-rev",
        "x-fb-trace-id",
    }
    return {key.lower(): value for key, value in headers.items() if key.lower() in allowed}
