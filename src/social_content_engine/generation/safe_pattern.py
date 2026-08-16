"""Generation-safe structural Pattern DTO with no source retrieval capability."""

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping

_FORBIDDEN_KEYS = {
    "text", "source_text", "quote", "url", "post_url", "permalink", "username",
    "author", "author_id", "source_post_id", "normalized_post_version_id",
    "structural_feature_instance_id", "embedding", "embedding_id", "retrieval_handle",
}


def _reject_source_fields(value: Any) -> None:
    if isinstance(value, Mapping):
        if _FORBIDDEN_KEYS.intersection(value):
            raise ValueError("generation-safe pattern cannot contain source fields")
        for child in value.values():
            _reject_source_fields(child)
    elif isinstance(value, list):
        for child in value:
            _reject_source_fields(child)


@dataclass(frozen=True)
class GenerationSafePattern:
    """An abstract pattern only; it cannot name or retrieve a source post."""

    pattern_kind: str
    component_sequence: List[str]
    abstract_formula: str
    support_count: int
    confidence: str
    taxonomy_version: str
    extractor_version: str
    performance_statistics: Dict[str, int]

    @classmethod
    def from_aggregate(cls, value: Mapping[str, Any]) -> "GenerationSafePattern":
        _reject_source_fields(value)
        required = {
            "pattern_kind", "component_sequence", "abstract_formula", "support_count",
            "confidence", "taxonomy_version", "extractor_version", "performance_statistics",
        }
        if set(value) != required:
            raise ValueError("generation-safe pattern contract mismatch")
        sequence = value["component_sequence"]
        statistics = value["performance_statistics"]
        if (
            not isinstance(sequence, list) or not sequence or
            not all(isinstance(item, str) for item in sequence) or
            not isinstance(statistics, dict) or
            not all(
                isinstance(item, int) and not isinstance(item, bool)
                for item in statistics.values()
            )
        ):
            raise ValueError("generation-safe pattern values are invalid")
        return cls(
            pattern_kind=str(value["pattern_kind"]),
            component_sequence=list(sequence),
            abstract_formula=str(value["abstract_formula"]),
            support_count=int(value["support_count"]),
            confidence=str(value["confidence"]),
            taxonomy_version=str(value["taxonomy_version"]),
            extractor_version=str(value["extractor_version"]),
            performance_statistics=dict(statistics),
        )

    def as_dict(self) -> Dict[str, Any]:
        return {
            "pattern_kind": self.pattern_kind,
            "component_sequence": list(self.component_sequence),
            "abstract_formula": self.abstract_formula,
            "support_count": self.support_count,
            "confidence": self.confidence,
            "taxonomy_version": self.taxonomy_version,
            "extractor_version": self.extractor_version,
            "performance_statistics": dict(self.performance_statistics),
        }
