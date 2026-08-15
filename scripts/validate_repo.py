"""Validate JSON syntax, schemas, fixtures, secrets, and task dependencies."""

import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, List

import jsonschema

from social_content_engine.data.normalize import normalize_threads_post

ROOT = Path(__file__).resolve().parents[1]
HEXISH_TOKEN = re.compile(
    r"(?i)(access[_-]?token|client[_-]?secret|api[_-]?key)\s*[=:]\s*['\"]?[^\s'\"]{20,}"
)


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_json_files(errors: List[str]) -> None:
    for path in sorted(ROOT.rglob("*.json")):
        if any(part in {".git", ".venv"} for part in path.parts):
            continue
        try:
            load(path)
        except (OSError, json.JSONDecodeError) as error:
            errors.append(str(path.relative_to(ROOT)) + ": " + str(error))


def validate_contracts(errors: List[str]) -> None:
    contracts = ROOT / "spec" / "contracts"
    for path in sorted(contracts.glob("*.schema.json")):
        schema = load(path)
        try:
            jsonschema.Draft202012Validator.check_schema(schema)
        except jsonschema.SchemaError as error:
            errors.append(str(path.relative_to(ROOT)) + ": " + error.message)

    fixture_bytes = (ROOT / "tests" / "fixtures" / "threads_keyword_search.json").read_bytes()
    fixture = json.loads(fixture_bytes)
    raw_capture = {
        "schema_version": 1,
        "source": "threads",
        "endpoint": "/keyword_search",
        "retrieved_at": "2026-08-15T00:00:01+00:00",
        "request": {"params": {"q": "fixture", "search_type": "RECENT"}},
        "http": {"status": 200, "headers": {"content-type": "application/json"}},
        "raw_response_sha256": hashlib.sha256(fixture_bytes).hexdigest(),
        "collector_version": "fixture",
        "response": fixture,
    }
    normalized = normalize_threads_post(
        fixture["data"][0],
        hashlib.sha256(
            json.dumps(
                fixture["data"][0], ensure_ascii=False, separators=(",", ":"), sort_keys=True
            ).encode("utf-8")
        ).hexdigest(),
        "2026-08-15T00:00:01+00:00",
    )
    instances = [
        ("raw capture", contracts / "raw-capture.schema.json", raw_capture),
        ("normalized post", contracts / "normalized-post.schema.json", normalized),
    ]
    for label, schema_path, instance in instances:
        try:
            jsonschema.Draft202012Validator(
                load(schema_path), format_checker=jsonschema.FormatChecker()
            ).validate(instance)
        except jsonschema.ValidationError as error:
            errors.append(label + " fixture: " + error.message)


def validate_capabilities(errors: List[str]) -> None:
    matrix = load(ROOT / "spec" / "THREADS_API_CAPABILITIES.json")
    valid = set(matrix["status_definitions"])
    names = set()
    for item in matrix["capabilities"]:
        if item["status"] not in valid:
            errors.append("invalid capability status: " + item["capability"])
        if item["capability"] in names:
            errors.append("duplicate capability: " + item["capability"])
        names.add(item["capability"])


def validate_tasks(errors: List[str]) -> None:
    tasks = load(ROOT / "spec" / "TASKS.json")["tasks"]
    ids = {item["id"] for item in tasks}
    for item in tasks:
        missing = set(item["depends_on"]) - ids
        if missing:
            errors.append(item["id"] + " has missing dependencies: " + repr(sorted(missing)))


def scan_secrets(errors: List[str]) -> None:
    suffixes = {
        ".py",
        ".md",
        ".json",
        ".toml",
        ".yml",
        ".yaml",
        ".sh",
        ".txt",
        ".env",
        ".example",
    }
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.suffix not in suffixes:
            continue
        if any(part in {".git", ".venv"} for part in path.parts):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if HEXISH_TOKEN.search(text):
            errors.append("possible committed secret: " + str(path.relative_to(ROOT)))


def main() -> int:
    errors: List[str] = []
    validate_json_files(errors)
    validate_contracts(errors)
    validate_capabilities(errors)
    validate_tasks(errors)
    scan_secrets(errors)
    if errors:
        print("Repository validation failed:", file=sys.stderr)
        for error in errors:
            print("- " + error, file=sys.stderr)
        return 1
    print("Repository validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
