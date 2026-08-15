"""M1 Analyzer Output schema loading and structural validation."""

import json
from pathlib import Path
from typing import Any, Dict

import jsonschema  # type: ignore[import-untyped]

TAXONOMY_VERSION = "M1_TAXONOMY_V1"
SCHEMA_PATH = (
    Path(__file__).resolve().parents[3]
    / "spec"
    / "contracts"
    / "analyzer-output.schema.json"
)


def load_output_schema() -> Dict[str, Any]:
    """Load the repository-owned Analyzer Output contract."""
    value: Dict[str, Any] = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    return value


def output_validator() -> jsonschema.Draft202012Validator:
    """Return a strict validator including RFC 3339 date-time checks."""
    return jsonschema.Draft202012Validator(
        load_output_schema(), format_checker=jsonschema.FormatChecker()
    )


def validate_output_contract(candidate: Dict[str, Any]) -> None:
    """Raise ValidationError when candidate violates the M1 output contract."""
    output_validator().validate(candidate)
