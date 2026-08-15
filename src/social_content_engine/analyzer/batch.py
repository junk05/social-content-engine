"""Restartable deterministic analysis over a finalized dataset snapshot."""

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from social_content_engine.data.repository import Repository

from .adapter import AnalyzerAdapter
from .orchestrator import analyze_normalized_version
from .validation import AnalyzerOutputError


@dataclass(frozen=True)
class BatchResult:
    batch_id: int
    status: str
    succeeded: int
    failed: int
    skipped: int


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def run_analysis_batch(
    repository: Repository,
    batch_id: int,
    adapter: AnalyzerAdapter,
    *,
    now: Callable[[], str] = _utc_now,
    new_run_id: Callable[[], str] = lambda: str(uuid.uuid4()),
) -> BatchResult:
    """Run pending/failed items; successful items are immutable restart checkpoints."""
    batch = repository.get_analysis_batch(batch_id)
    if batch["model_provider"] != "deterministic" or batch["model_name"] != "mock":
        raise ValueError("M2 analysis batches support deterministic/mock only")
    repository.restart_analysis_batch(batch_id)
    total = int(
        repository.connection.execute(
            "SELECT COUNT(*) FROM analysis_batch_items WHERE analysis_batch_id = ?",
            (batch_id,),
        ).fetchone()[0]
    )
    items = repository.pending_analysis_batch_items(batch_id)
    skipped = total - len(items)
    succeeded = 0
    failed = 0
    for item in items:
        item_id = int(item["id"])
        version_id = int(item["normalized_post_version_id"])
        started_at = now()
        repository.start_analysis_batch_item(item_id, started_at=started_at)
        prior_max_run_id = int(
            repository.connection.execute(
                "SELECT COALESCE(MAX(id), 0) FROM analysis_runs"
            ).fetchone()[0]
        )
        try:
            result = analyze_normalized_version(
                repository,
                version_id,
                adapter,
                analyzer_version=str(batch["analyzer_version"]),
                taxonomy_version=str(batch["taxonomy_version"]),
                prompt_version=str(batch["prompt_version"]),
                model_provider=str(batch["model_provider"]),
                model_name=str(batch["model_name"]),
                model_parameters=batch["model_parameters"],
                new_run_id=new_run_id,
                now=now,
            )
            repository.finish_analysis_batch_item(
                item_id, result.analysis_run_row_id, completed_at=now()
            )
            succeeded += 1
        except Exception as error:
            error_code = error.code if isinstance(error, AnalyzerOutputError) else "ADAPTER_ERROR"
            run = repository.connection.execute(
                """SELECT id FROM analysis_runs
                WHERE normalized_post_version_id = ? AND id > ?
                ORDER BY id DESC LIMIT 1""",
                (version_id, prior_max_run_id),
            ).fetchone()
            repository.fail_analysis_batch_item(
                item_id,
                error_code,
                completed_at=now(),
                analysis_run_row_id=int(run["id"]) if run is not None else None,
            )
            failed += 1
    status = repository.finalize_analysis_batch(batch_id, completed_at=now())
    return BatchResult(batch_id, status, succeeded, failed, skipped)
