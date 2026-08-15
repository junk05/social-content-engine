"""Semantic validation for M1 Analyzer candidate output."""

from typing import Any, Dict, Mapping

import jsonschema  # type: ignore[import-untyped]

from .adapter import AnalysisContext
from .contracts import validate_output_contract


class AnalyzerOutputError(ValueError):
    """A rejected analyzer candidate with a stable persisted error code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _validate_metadata(
    candidate: Mapping[str, Any], analyzer_input: Mapping[str, Any], context: AnalysisContext
) -> None:
    expected = {
        "analysis_run_id": context.analysis_run_id,
        "source_post_id": analyzer_input["source_post_id"],
        "taxonomy_version": context.taxonomy_version,
        "analyzer_version": context.analyzer_version,
        "prompt_version": context.prompt_version,
        "input_sha256": context.input_sha256,
        "analyzed_at": context.analyzed_at,
    }
    for field, value in expected.items():
        if candidate.get(field) != value:
            raise AnalyzerOutputError("METADATA_MISMATCH", field + " does not match run context")
    expected_model = {
        "provider": context.model_provider,
        "name": context.model_name,
        "parameters": dict(context.model_parameters),
    }
    if candidate.get("model") != expected_model:
        raise AnalyzerOutputError("METADATA_MISMATCH", "model does not match run context")


def _validate_evidence(candidate: Mapping[str, Any], text: str) -> None:
    for collection in ("actions", "psychology_hypotheses", "structures"):
        for item in candidate[collection]:
            for evidence in item["evidence"]:
                start = evidence["start"]
                end = evidence["end"]
                if start >= end or end > len(text):
                    raise AnalyzerOutputError(
                        "INVALID_EVIDENCE_SPAN", collection + " evidence is outside source text"
                    )
                if text[start:end] != evidence["quote"]:
                    raise AnalyzerOutputError(
                        "EVIDENCE_QUOTE_MISMATCH",
                        collection + " quote does not equal source text span",
                    )


def _validate_content(candidate: Mapping[str, Any], text: str) -> None:
    content = candidate["content"]
    values = list(content["entities"])
    values.extend(content["keywords"])
    folded_text = text.casefold()
    for value in values:
        if value and value.casefold() not in folded_text:
            raise AnalyzerOutputError(
                "UNSUPPORTED_CONTENT", "content value is not observable in source text: " + value
            )


def validate_analyzer_output(
    candidate: Dict[str, Any], analyzer_input: Mapping[str, Any], context: AnalysisContext
) -> None:
    """Reject invalid schema, provenance, evidence, or unsupported content."""
    try:
        validate_output_contract(candidate)
    except jsonschema.ValidationError as error:
        raise AnalyzerOutputError("INVALID_SCHEMA", error.message) from error
    _validate_metadata(candidate, analyzer_input, context)
    text = str(analyzer_input["text"])
    _validate_evidence(candidate, text)
    _validate_content(candidate, text)
