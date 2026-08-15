import copy
import json
import unittest
from pathlib import Path

import jsonschema

ROOT = Path(__file__).parents[1]


class ContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.schema = json.loads(
            (ROOT / "spec" / "contracts" / "normalized-post.schema.json").read_text()
        )
        self.validator = jsonschema.Draft202012Validator(
            self.schema, format_checker=jsonschema.FormatChecker()
        )
        self.valid = {
            "schema_version": 1,
            "source": "threads",
            "source_post_id": "fixture-1",
            "author_id": None,
            "username": None,
            "text": None,
            "permalink": None,
            "published_at": None,
            "media_type": None,
            "raw_sha256": "0" * 64,
            "normalized_at": "2026-08-15T00:00:00+00:00",
        }

    def test_rejects_invalid_hash(self) -> None:
        instance = copy.deepcopy(self.valid)
        instance["raw_sha256"] = "not-a-hash"
        self.assertTrue(list(self.validator.iter_errors(instance)))

    def test_rejects_invalid_datetime(self) -> None:
        instance = copy.deepcopy(self.valid)
        instance["normalized_at"] = "yesterday"
        self.assertTrue(list(self.validator.iter_errors(instance)))

    def test_rejects_extra_field(self) -> None:
        instance = copy.deepcopy(self.valid)
        instance["invented_metric"] = 123
        self.assertTrue(list(self.validator.iter_errors(instance)))


if __name__ == "__main__":
    unittest.main()
