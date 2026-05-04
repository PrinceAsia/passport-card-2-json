"""Auto-detect the document type from OCR text + MRZ presence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.core.mrz_parser import MrzResult

DocType = Literal["passport", "id_card", "birth_certificate", "unknown"]


@dataclass(frozen=True, slots=True)
class ClassificationResult:
    """Output of `classify_document`."""

    document_type: DocType
    confidence: float


# Keyword sets — case-insensitive, normalized text only.
_PASSPORT_KEYWORDS = (
    "passport",
    "паспорт",
    "pasport",
    "pasporti",
    "republic of uzbekistan",
    "ozbekiston respublikasi",
    "respublikasining fuqarosi",
)
_ID_CARD_KEYWORDS = (
    "id card",
    "id-card",
    "id number",
    "shaxsiy guvohnoma",
    "shaxsiy guvohnomasi",
    "shaxs guvohnomasi",
    "shaxsiy raqami",
    "shaxsiy varaqa",
    "id karta",
    "id-karta",
    "id-карта",
    "удостоверение личности",
    "personallashtirish organi",
)
_BIRTH_CERT_KEYWORDS = (
    "birth certificate",
    "tug'ilganlik haqida guvohnoma",
    "tug'ilganlik guvohnomasi",
    "tug ilganlik",
    "tugilganlik",
    "свидетельство о рождении",
    "о рождении",
    "fhdyo",
)


def _count_hits(haystack: str, needles: tuple[str, ...]) -> int:
    """Return the number of keywords in `needles` that appear in `haystack`."""
    return sum(1 for n in needles if n in haystack)


def classify_document(text: str, mrz: MrzResult | None) -> ClassificationResult:
    """Classify document type using MRZ format + keyword heuristics.

    Args:
        text: Concatenated OCR text from all pages (lower-cased internally).
        mrz: Parsed MRZ result if any was found.

    Returns:
        Detected type + a confidence score in [0.0, 1.0].
    """
    haystack = text.lower()

    # MRZ format alone is a very strong signal.
    if mrz is not None:
        if mrz.format == "TD3":
            return ClassificationResult("passport", 0.97 if mrz.check_digits_valid else 0.85)
        if mrz.format == "TD1":
            return ClassificationResult("id_card", 0.97 if mrz.check_digits_valid else 0.85)

    passport_hits = _count_hits(haystack, _PASSPORT_KEYWORDS)
    id_hits = _count_hits(haystack, _ID_CARD_KEYWORDS)
    birth_hits = _count_hits(haystack, _BIRTH_CERT_KEYWORDS)

    scores: dict[DocType, int] = {
        "passport": passport_hits,
        "id_card": id_hits,
        "birth_certificate": birth_hits,
    }
    best = max(scores, key=lambda k: scores[k])
    if scores[best] == 0:
        return ClassificationResult("unknown", 0.0)

    total = sum(scores.values()) or 1
    confidence = min(0.85, 0.4 + 0.15 * scores[best] + 0.1 * (scores[best] / total))
    return ClassificationResult(best, round(confidence, 2))
