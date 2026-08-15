"""Deterministic Analyzer adapter for tests and local fixture execution."""

import re
from typing import Any, Dict, List, Mapping, Optional, Tuple

from .adapter import AnalysisContext


def _first_span(text: str, needles: Tuple[str, ...]) -> Optional[Dict[str, Any]]:
    matches = [(text.find(needle), needle) for needle in needles if needle in text]
    if not matches:
        return None
    start, quote = min(matches, key=lambda item: item[0])
    return {"quote": quote, "start": start, "end": start + len(quote)}


def _item(label: str, confidence: str, evidence: Dict[str, Any]) -> Dict[str, Any]:
    return {"label": label, "confidence": confidence, "evidence": [evidence]}


class DeterministicMockAdapter:
    """Emit bounded fixture candidates from explicit text markers only."""

    def analyze(
        self, analyzer_input: Mapping[str, Any], context: AnalysisContext
    ) -> Dict[str, Any]:
        text = str(analyzer_input["text"])
        actions: List[Dict[str, Any]] = []
        structures: List[Dict[str, Any]] = []
        psychology: List[Dict[str, Any]] = []

        question = _first_span(text, ("？", "?"))
        if question:
            actions.append(_item("ASK", "HIGH", question))
            structures.append(_item("QUESTION_LED", "HIGH", question))

        experience = _first_span(text, ("私は", "ました", "だった"))
        if experience:
            actions.append(_item("SHARE_EXPERIENCE", "HIGH", experience))

        advice = _first_span(text, ("してください", "おすすめ", "べき"))
        if advice:
            actions.append(_item("ADVISE", "HIGH", advice))
            structures.append(_item("PROBLEM_SOLUTION", "MEDIUM", advice))

        emotion_map = (
            ("FRUSTRATION", ("つらい", "悔しい")),
            ("FEAR_OR_ANXIETY_EXPRESSED", ("不安", "怖い")),
            ("HOPE", ("うれしい", "嬉しい", "楽しみ")),
        )
        for label, needles in emotion_map:
            evidence = _first_span(text, needles)
            if evidence:
                actions.append(_item("EXPRESS_EMOTION", "HIGH", evidence))
                hypothesis = _item(label, "MEDIUM", evidence)
                hypothesis["inference"] = True
                psychology.append(hypothesis)
                break

        if text and len(text) <= 80:
            evidence = {"quote": text, "start": 0, "end": len(text)}
            structures.append(_item("SHORT_PUNCHY", "HIGH", evidence))

        hashtags = re.findall(r"(?<!\w)#([\w]+)", text)
        words = re.findall(r"[\w一-龯ぁ-んァ-ヶー]{2,}", text)
        primary_topic = hashtags[0] if hashtags else (words[0][:24] if words else "")
        keywords = list(dict.fromkeys(hashtags + words))[:10]

        return {
            "schema_version": 1,
            "analysis_run_id": context.analysis_run_id,
            "source_post_id": str(analyzer_input["source_post_id"]),
            "taxonomy_version": context.taxonomy_version,
            "analyzer_version": context.analyzer_version,
            "prompt_version": context.prompt_version,
            "model": {
                "provider": context.model_provider,
                "name": context.model_name,
                "parameters": dict(context.model_parameters),
            },
            "input_sha256": context.input_sha256,
            "actions": actions,
            "psychology_hypotheses": psychology,
            "structures": structures,
            "content": {
                "primary_topic": primary_topic,
                "secondary_topics": hashtags[1:],
                "entities": [],
                "keywords": keywords,
            },
            "warnings": [],
            "analyzed_at": context.analyzed_at,
        }
