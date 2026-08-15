"""Bounded, resumable keyword-search pagination without persistence side effects."""

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple

from .client import HttpCapture


@dataclass(frozen=True)
class SearchJob:
    query: str
    search_type: str


@dataclass(frozen=True)
class CollectionPlan:
    queries: Sequence[str]
    search_types: Sequence[str] = ("RECENT", "TOP")
    search_mode: str = "KEYWORD"
    fields: str = "id,media_type,permalink,owner,username,text,timestamp"
    since: str = ""
    until: str = ""
    page_limit: int = 50
    target_unique: int = 100
    hard_cap: int = 200
    max_requests: int = 8
    live_interval_seconds: float = 2.0

    def validate(self) -> None:
        if not self.queries or any(not query for query in self.queries):
            raise ValueError("queries must contain non-empty values")
        if not self.search_types or any(
            value not in {"TOP", "RECENT"} for value in self.search_types
        ):
            raise ValueError("search_types must contain only TOP or RECENT")
        if self.search_mode not in {"KEYWORD", "TAG"}:
            raise ValueError("search_mode must be KEYWORD or TAG")
        if self.page_limit < 1 or self.page_limit > 50:
            raise ValueError("page_limit must be between 1 and 50")
        if min(self.target_unique, self.hard_cap, self.max_requests) < 1:
            raise ValueError("collection bounds must be positive")
        if self.live_interval_seconds < 2:
            raise ValueError("live_interval_seconds must be at least 2")

    def jobs(self) -> List[SearchJob]:
        return [
            SearchJob(query, search_type)
            for query in self.queries
            for search_type in self.search_types
        ]


Fetch = Callable[..., HttpCapture]
Sleep = Callable[[float], None]


def collect(
    plan: CollectionPlan,
    fetch: Fetch,
    *,
    checkpoint_path: Optional[Path] = None,
    resume: bool = False,
    sleep: Sleep = time.sleep,
) -> Dict[str, Any]:
    """Run a deterministic bounded plan; ``fetch`` may be a live client or fixture."""
    plan.validate()
    fingerprint = _fingerprint(plan)
    state = _load_checkpoint(checkpoint_path, fingerprint) if resume else _new_state(fingerprint)
    jobs = plan.jobs()
    seen: Set[str] = set(state["seen_ids"])
    stop_reason = "PLAN_EXHAUSTED"

    while state["job_index"] < len(jobs):
        if len(seen) >= plan.target_unique:
            stop_reason = "TARGET_REACHED"
            break
        if len(seen) >= plan.hard_cap:
            stop_reason = "HARD_CAP_REACHED"
            break
        if state["request_count"] >= plan.max_requests:
            stop_reason = "REQUEST_CAP_REACHED"
            break

        job = jobs[state["job_index"]]
        if state["request_count"] and plan.live_interval_seconds:
            sleep(plan.live_interval_seconds)
        capture = fetch(
            query=job.query,
            search_type=job.search_type,
            search_mode=plan.search_mode,
            fields=plan.fields,
            since=plan.since,
            until=plan.until,
            limit=plan.page_limit,
            after=state["after"],
        )
        state["request_count"] += 1
        state["http_statuses"].append(capture.status)
        if capture.status < 200 or capture.status >= 300:
            state["job_stops"].append(_job_stop(job, "HTTP_ERROR"))
            stop_reason = "HTTP_ERROR"
            _save_checkpoint(checkpoint_path, state, seen)
            break

        try:
            payload = json.loads(capture.body.decode("utf-8"))
            items, cursor_status, after = _extract_page(payload)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            state["job_stops"].append(_job_stop(job, "INVALID_RESPONSE"))
            stop_reason = "INVALID_RESPONSE"
            _save_checkpoint(checkpoint_path, state, seen)
            break

        state["page_count"] += 1
        if not items:
            state["job_stops"].append(_job_stop(job, "EMPTY_PAGE"))
            _advance_job(state)
            _save_checkpoint(checkpoint_path, state, seen)
            continue

        for item in items:
            post_id = item.get("id")
            if not isinstance(post_id, str) or not post_id:
                state["job_stops"].append(_job_stop(job, "INVALID_RESPONSE"))
                stop_reason = "INVALID_RESPONSE"
                _save_checkpoint(checkpoint_path, state, seen)
                return _summary(state, seen, stop_reason)
            state["observation_count"] += 1
            if post_id not in seen and len(seen) < plan.hard_cap:
                seen.add(post_id)

        if len(seen) >= plan.target_unique:
            stop_reason = "TARGET_REACHED"
        elif len(seen) >= plan.hard_cap:
            stop_reason = "HARD_CAP_REACHED"
        elif cursor_status != "cursor":
            state["job_stops"].append(_job_stop(job, cursor_status))
            _advance_job(state)
        elif after in state["used_cursors"]:
            state["job_stops"].append(_job_stop(job, "REPEATED_CURSOR"))
            _advance_job(state)
        else:
            state["used_cursors"].append(after)
            state["after"] = after
        _save_checkpoint(checkpoint_path, state, seen)
        if stop_reason != "PLAN_EXHAUSTED":
            break

    return _summary(state, seen, stop_reason)


def summary_json(summary: Dict[str, Any]) -> str:
    return json.dumps(summary, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"


def _extract_page(payload: Any) -> Tuple[List[Dict[str, Any]], str, str]:
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise ValueError("response data must be a list")
    items = payload["data"]
    if any(not isinstance(item, dict) for item in items):
        raise ValueError("response items must be objects")
    if "paging" not in payload:
        return items, "NO_NEXT_CURSOR", ""
    paging = payload["paging"]
    if not isinstance(paging, dict) or not isinstance(paging.get("cursors"), dict):
        raise ValueError("paging.cursors must be an object")
    cursors = paging["cursors"]
    if "after" not in cursors:
        return items, "NO_NEXT_CURSOR", ""
    after = cursors["after"]
    if after is None or after == "":
        return items, "NO_NEXT_CURSOR", ""
    if not isinstance(after, str):
        raise ValueError("after cursor must be a string")
    return items, "cursor", after


def _fingerprint(plan: CollectionPlan) -> str:
    value = {
        "fields": plan.fields,
        "hard_cap": plan.hard_cap,
        "max_requests": plan.max_requests,
        "page_limit": plan.page_limit,
        "queries": list(plan.queries),
        "search_mode": plan.search_mode,
        "search_types": list(plan.search_types),
        "since": plan.since,
        "target_unique": plan.target_unique,
        "until": plan.until,
    }
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode("utf-8")).hexdigest()


def _new_state(fingerprint: str) -> Dict[str, Any]:
    return {
        "schema_version": 1,
        "plan_fingerprint": fingerprint,
        "job_index": 0,
        "after": "",
        "used_cursors": [],
        "seen_ids": [],
        "request_count": 0,
        "page_count": 0,
        "observation_count": 0,
        "http_statuses": [],
        "job_stops": [],
    }


def _load_checkpoint(path: Optional[Path], fingerprint: str) -> Dict[str, Any]:
    if path is None or not path.exists():
        return _new_state(fingerprint)
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("plan_fingerprint") != fingerprint:
        raise ValueError("checkpoint does not match collection plan")
    return value


def _save_checkpoint(path: Optional[Path], state: Dict[str, Any], seen: Set[str]) -> None:
    state["seen_ids"] = sorted(seen)
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(summary_json(state), encoding="utf-8")


def _advance_job(state: Dict[str, Any]) -> None:
    state["job_index"] += 1
    state["after"] = ""
    state["used_cursors"] = []


def _job_stop(job: SearchJob, reason: str) -> Dict[str, str]:
    return {"query": job.query, "search_type": job.search_type, "reason": reason}


def _summary(state: Dict[str, Any], seen: Set[str], stop_reason: str) -> Dict[str, Any]:
    return {
        "schema_version": 1,
        "stop_reason": stop_reason,
        "unique_count": len(seen),
        "observation_count": state["observation_count"],
        "request_count": state["request_count"],
        "page_count": state["page_count"],
        "seen_ids": sorted(seen),
        "http_statuses": list(state["http_statuses"]),
        "job_stops": list(state["job_stops"]),
    }
