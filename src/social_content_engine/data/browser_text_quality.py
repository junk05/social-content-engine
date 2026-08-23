"""Deterministic, audit-safe text quality classification for browser evidence."""

import re

VALID_TEXT = "VALID_TEXT"
INVALID_TEXT_DATE_METADATA = "INVALID_TEXT_DATE_METADATA"
INVALID_TEXT_TOPIC_TAG_METADATA = "INVALID_TEXT_TOPIC_TAG_METADATA"
TEXT_UNAVAILABLE = "TEXT_UNAVAILABLE"
ASSESSOR_VERSION = "m4-browser-text-quality-v1"

_ABSOLUTE_DATE = re.compile(r"^\d{4}[/-]\d{1,2}[/-]\d{1,2}$")
_RELATIVE_TIME = re.compile(
    r"^(?:\d+\s*(?:分|時間|日|週|ヶ月|か月|月|年|m|min|h|d|w|mo|y)|昨日|一昨日)$",
    re.IGNORECASE,
)


def classify_browser_text_quality(text: object) -> str:
    """Classify only observable legacy text defects; never infer replacement text."""
    if not isinstance(text, str) or not text.strip():
        return TEXT_UNAVAILABLE
    value = text.strip()
    if _ABSOLUTE_DATE.fullmatch(value) or _RELATIVE_TIME.fullmatch(value):
        return INVALID_TEXT_DATE_METADATA
    return VALID_TEXT
