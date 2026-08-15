"""M1 Analyzer orchestration, replay, and failure provenance."""

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict

from social_content_engine.data.repository import Repository

from .adapter import AnalysisContext, AnalyzerAdapter
from .contracts import TAXONOMY_VERSION
from .preprocessing import build_analyzer_input, input_sha256
from .validation import AnalyzerOutputError, validate_analyzer_output

ANALYZER_VERSION = "m1-analyzer-v1"
PROMPT_VERSION = "m1-mock-prompt-v1"
MODEL_PROVIDER = "deterministic"
MODEL_NAME = "mock"
MODEL_PARAMETERS: Dict[str, Any] = {}


@dataclass(frozen=True)
class AnalysisResult:
    analysis_run_id: str
    payload: Dict[str, Any]
    reused: bool


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def analyze_post(
    repository: Repository,
    post_id: str,
    adapter: AnalyzerAdapter,
    *,
    force: bool = False,
    now: Callable[[], str] = _utc_now,
    new_run_id: Callable[[], str] = lambda: str(uuid.uuid4()),
) -> AnalysisResult:
    """Analyze one normalized post, reusing an identical success unless forced."""
    post = repository.get_normalized_post(post_id)
    analyzer_input = build_analyzer_input(post)
    input_hash = input_sha256(analyzer_input)
    identity = {
        "source": post["source"],
        "source_post_id": post["source_post_id"],
        "analyzer_version": ANALYZER_VERSION,
        "taxonomy_version": TAXONOMY_VERSION,
        "prompt_version": PROMPT_VERSION,
        "model_name": MODEL_NAME,
        "model_parameters": MODEL_PARAMETERS,
        "input_sha256": input_hash,
    }
    if not force:
        reusable = repository.find_reusable_analysis(identity)
        if reusable is not None:
            return AnalysisResult(
                analysis_run_id=reusable["analysis_run_id"],
                payload=reusable["payload"],
                reused=True,
            )

    run_id = new_run_id()
    analyzed_at = now()
    context = AnalysisContext(
        run_id,
        ANALYZER_VERSION,
        TAXONOMY_VERSION,
        PROMPT_VERSION,
        MODEL_PROVIDER,
        MODEL_NAME,
        MODEL_PARAMETERS,
        input_hash,
        analyzed_at,
    )
    row_id = repository.start_analysis_run(
        {
            "analysis_run_id": run_id,
            "source": post["source"],
            "source_post_id": post["source_post_id"],
            "normalized_post_version": post["normalized_post_version"],
            "analyzer_version": ANALYZER_VERSION,
            "taxonomy_version": TAXONOMY_VERSION,
            "prompt_version": PROMPT_VERSION,
            "model_provider": MODEL_PROVIDER,
            "model_name": MODEL_NAME,
            "model_parameters": MODEL_PARAMETERS,
            "input_sha256": input_hash,
            "analyzed_at": analyzed_at,
        }
    )
    try:
        candidate = adapter.analyze(analyzer_input, context)
        if not isinstance(candidate, dict):
            raise AnalyzerOutputError("INVALID_JSON", "adapter output must be a JSON object")
        validate_analyzer_output(candidate, analyzer_input, context)
        output_hash = input_sha256(candidate)
        repository.persist_analysis(row_id, post_id, candidate, output_hash)
    except AnalyzerOutputError as error:
        repository.fail_analysis_run(row_id, error.code)
        raise
    except Exception:
        repository.fail_analysis_run(row_id, "ADAPTER_ERROR")
        raise
    return AnalysisResult(run_id, candidate, False)
