"""Base abstractions for per-document extractors.

The helpers in `BaseExtractor` provide the heavy lifting for label-driven field
extraction. Real OCR output for Uzbek documents has labels in mixed scripts
("ФАМИЛИЯСИ /SURNAME") on one line and the value on the *next* line, often
prefixed or suffixed with stray glyphs. We model both shapes:

- `find_value_after_label`: label keyword somewhere on a line; value is the
  next non-empty line (preferred), or the trailing tokens on the same line.
- `find_inline_value`: explicit `label: value` or `label - value`.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from app.core.mrz_parser import MrzResult


@dataclass(frozen=True, slots=True)
class ExtractionContext:
    """Inputs available to an extractor for a single document."""

    raw_text: str
    raw_text_per_page: list[str]
    word_boxes: list[dict[str, Any]] = field(default_factory=list)
    mrz: MrzResult | None = None


class BaseExtractor(ABC):
    """Subclass per document type. Pure functions of `ExtractionContext`."""

    @abstractmethod
    def extract(self, ctx: ExtractionContext) -> tuple[BaseModel, list[str]]:
        """Return (typed fields model, list of low-confidence field names).

        Subclasses tighten the return type to a concrete `BaseModel` subclass.
        """

    # ------------------------------------------------------------------ #
    # Label-driven helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _strip_value(value: str) -> str:
        """Trim noise glyphs that OCR commonly attaches to field values."""
        # Drop leading/trailing punctuation, single-char Cyrillic/Latin tokens
        # that are obvious page numbers / margin marks.
        value = value.strip(" \t.,;:|/\\\"'·*-_~`")
        return re.sub(r"\s+", " ", value)

    @staticmethod
    def find_inline_value(text: str, labels: tuple[str, ...]) -> str | None:
        """Return the text after `label:` / `label-` on the same line."""
        for raw_line in text.splitlines():
            line = _normalize_for_match(raw_line)
            for label in labels:
                lbl = _normalize_for_match(label)
                pattern = re.compile(rf"{re.escape(lbl)}\s*[:\-]\s*(.+)", flags=re.IGNORECASE)
                m = pattern.search(line)
                if m:
                    cleaned = BaseExtractor._strip_value(m.group(1))
                    if cleaned:
                        return cleaned
        return None

    @staticmethod
    def find_value_after_label(
        text: str,
        labels: tuple[str, ...],
        *,
        max_lookahead: int = 3,
        value_pattern: re.Pattern[str] | None = None,
    ) -> str | None:
        """Locate a label and return the most plausible following value.

        Strategy:
        - If `value_pattern` is given (e.g. a date regex), prefer an inline
          match on the label line; fall back to scanning the next lines.
        - Otherwise, prefer the next non-empty/non-label line; fall back to
          a long enough trailing inline token. This avoids cases where OCR
          attaches a 1-character glyph (`u`, `р`) right after the label.

        Args:
            text: Full OCR text (multi-line).
            labels: Candidate label tokens, case-insensitive. Apostrophes are
                normalized so OCR variants like `tug'ilgan'sanasi` still match
                a label registered as `tug'ilgan sanasi`.
            max_lookahead: How many subsequent non-empty lines to consider.
            value_pattern: Optional regex; matches must satisfy `.search()`.
        """
        lines = text.splitlines()
        normalized = [_normalize_for_match(line) for line in lines]
        lowered_labels = [_normalize_for_match(label) for label in labels]

        for i, norm in enumerate(normalized):
            for label in lowered_labels:
                pos = norm.find(label)
                if pos < 0:
                    continue

                inline = BaseExtractor._strip_value(lines[i][pos + len(label) :])
                next_line_value = _scan_next_lines(
                    lines, start=i + 1, lookahead=max_lookahead, pattern=value_pattern
                )

                if value_pattern is not None:
                    inline_match = _extract_match(inline, value_pattern) if inline else None
                    if inline_match and value_pattern.search(inline_match):
                        return inline_match
                    if next_line_value:
                        return next_line_value
                    continue

                # No pattern: prefer next-line, fall back to inline only when
                # inline is sufficiently substantive (>= 3 chars, not a label).
                if next_line_value:
                    return next_line_value
                if (
                    inline
                    and len(inline) >= 3
                    and not _looks_like_label(inline)
                ):
                    return inline
        return None

    @staticmethod
    def find_first(text: str, pattern: re.Pattern[str]) -> str | None:
        """Return the first regex match anywhere in `text` (group 1 if present)."""
        m = pattern.search(text)
        if not m:
            return None
        if m.groups():
            return m.group(1).strip()
        return m.group(0).strip()


# ---------------------------------------------------------------------- #
# Module-level helpers
# ---------------------------------------------------------------------- #

# Loose heuristic: is this candidate string itself a label rather than a value?
# Labels in Uzbek docs typically end with a slash group (`/SEX`) or contain a
# slash separator joining two scripts (`ФАМИЛИЯСИ/ФАМИЛИЯ`).
_LABEL_HINTS = (
    "surname",
    "given name",
    "given names",
    "nationality",
    "place of birth",
    "date of birth",
    "date of issue",
    "date of expiry",
    "authority",
    "sex",
    "familiya",
    "ismi",
    "millati",
    "tug'ilgan",
    "berilgan",
    "amal qilish",
    "shaxsiy raqami",
    "id number",
    "фамилия",
    "имя",
    "отчество",
    "национальность",
    "дата",
    "место",
    "ким томонидан",
)


def _looks_like_label(candidate: str) -> bool:
    """Best-effort check that `candidate` is a label rather than a value."""
    lowered = candidate.lower()
    if any(hint in lowered for hint in _LABEL_HINTS):
        return True
    # Strings containing only punctuation/digits-with-slashes are labels.
    return bool(re.fullmatch(r"[\s/\-_.|·]+", candidate))


def _extract_match(text: str, pattern: re.Pattern[str]) -> str:
    """Run the pattern against `text` and return group 1 or the full match."""
    m = pattern.search(text)
    if not m:
        return text
    return m.group(1) if m.groups() else m.group(0)


_APOSTROPHE_CLASS = re.compile(r"['ʻ‘’`´]")


def _normalize_for_match(text: str) -> str:
    """Lowercase + canonicalize apostrophes so labels match OCR variants."""
    return _APOSTROPHE_CLASS.sub("'", text).lower()


def _scan_next_lines(
    lines: list[str],
    *,
    start: int,
    lookahead: int,
    pattern: re.Pattern[str] | None,
) -> str | None:
    """Return the first non-label, non-empty line in the lookahead window."""
    checked = 0
    for j in range(start, len(lines)):
        candidate = BaseExtractor._strip_value(lines[j])
        if not candidate:
            continue
        checked += 1
        if checked > lookahead:
            break
        if _looks_like_label(candidate):
            continue
        if pattern is not None and not pattern.search(candidate):
            continue
        return _extract_match(candidate, pattern) if pattern is not None else candidate
    return None
