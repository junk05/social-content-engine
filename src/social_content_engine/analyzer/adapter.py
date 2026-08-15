"""Provider-independent Analyzer adapter boundary."""

from dataclasses import dataclass
from typing import Any, Dict, Mapping, Protocol


@dataclass(frozen=True)
class AnalysisContext:
    """Versioned metadata supplied by orchestration, never by provider secrets."""

    analysis_run_id: str
    analyzer_version: str
    taxonomy_version: str
    prompt_version: str
    model_provider: str
    model_name: str
    model_parameters: Mapping[str, Any]
    input_sha256: str
    analyzed_at: str


class AnalyzerAdapter(Protocol):
    """An adapter returns candidate JSON and performs no persistence."""

    def analyze(
        self, analyzer_input: Mapping[str, Any], context: AnalysisContext
    ) -> Dict[str, Any]: ...
