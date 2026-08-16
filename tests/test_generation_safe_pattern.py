import ast
import unittest
from pathlib import Path

from social_content_engine.generation.safe_pattern import GenerationSafePattern


class GenerationSafePatternTest(unittest.TestCase):
    def test_generation_dto_keeps_only_abstract_structural_fields(self) -> None:
        pattern = GenerationSafePattern.from_aggregate({
            "pattern_kind": "FIRST_LINE", "component_sequence": ["TARGET_READER", "QUESTION"],
            "abstract_formula": "TARGET_READER -> QUESTION", "support_count": 2,
            "confidence": "LOW", "taxonomy_version": "M4_STRUCTURAL_TAXONOMY_V1",
            "extractor_version": "m4-structural-extractor-v2",
            "performance_statistics": {"view_count_observed": 0},
        })
        self.assertNotIn("source_post_id", pattern.as_dict())
        self.assertNotIn("text", pattern.as_dict())

    def test_generation_dto_rejects_source_and_retrieval_fields(self) -> None:
        unsafe = {
            "pattern_kind": "FIRST_LINE", "component_sequence": ["QUESTION"],
            "abstract_formula": "QUESTION", "support_count": 2, "confidence": "LOW",
            "taxonomy_version": "M4_STRUCTURAL_TAXONOMY_V1",
            "extractor_version": "m4-structural-extractor-v2", "performance_statistics": {},
            "source_post_id": "forbidden",
        }
        with self.assertRaisesRegex(ValueError, "source"):
            GenerationSafePattern.from_aggregate(unsafe)

    def test_generation_package_cannot_import_source_storage(self) -> None:
        package = Path(__file__).parents[1] / "src/social_content_engine/generation"
        for path in package.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            imports = [
                node.module or "" for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom)
            ]
            self.assertFalse(any("data.repository" in item for item in imports), path.name)


if __name__ == "__main__":
    unittest.main()
