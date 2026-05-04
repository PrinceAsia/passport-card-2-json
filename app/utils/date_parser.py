"""Robust date parsing for Uzbek / Russian / English document strings.

Handles the formats commonly seen in OCR output:
    - 12.05.2010, 12/05/2010, 12-05-2010
    - 2010-05-12 (already ISO)
    - 12 май 2010, 12 may 2010, 12 may. 2010
    - 12 mart 2010 (Uzbek Latin)
    - 12 марта 2010 г.

If none of the candidate parses succeed, returns None — the caller is expected
to fall back to a `*_raw` field.
"""

from __future__ import annotations

import re
from datetime import date

from dateutil import parser as du_parser

# Map non-English month tokens to English so dateutil can handle them.
_MONTH_MAP = {
    # Uzbek Latin
    "yanvar": "January",
    "fevral": "February",
    "mart": "March",
    "aprel": "April",
    "may": "May",
    "iyun": "June",
    "iyul": "July",
    "avgust": "August",
    "sentyabr": "September",
    "sentabr": "September",
    "oktyabr": "October",
    "oktabr": "October",
    "noyabr": "November",
    "dekabr": "December",
    # Russian (lowercased; both nominative and genitive forms)
    "январь": "January",
    "января": "January",
    "февраль": "February",
    "февраля": "February",
    "март": "March",
    "марта": "March",
    "апрель": "April",
    "апреля": "April",
    "май": "May",
    "мая": "May",
    "июнь": "June",
    "июня": "June",
    "июль": "July",
    "июля": "July",
    "август": "August",
    "августа": "August",
    "сентябрь": "September",
    "сентября": "September",
    "октябрь": "October",
    "октября": "October",
    "ноябрь": "November",
    "ноября": "November",
    "декабрь": "December",
    "декабря": "December",
}

_TRAILING_YEAR_MARKERS = re.compile(r"\bг\.?\b|\byil\b|\byili\b", re.IGNORECASE)
_MMDDYY_NUMERIC = re.compile(r"^\d{1,2}[./\-\s]\d{1,2}[./\-\s]\d{2,4}$")
_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _replace_months(text: str) -> str:
    """Substitute uz/ru month names with their English equivalents."""
    lower = text.lower()
    for token, english in _MONTH_MAP.items():
        if token in lower:
            lower = lower.replace(token, english.lower())
    return lower


def parse_date(raw: str | None) -> date | None:
    """Best-effort parse a date string into a `datetime.date`.

    Args:
        raw: Free-form date string captured from OCR. May be None or empty.

    Returns:
        The parsed `date` on success; `None` if no candidate parse was viable.
    """
    if not raw:
        return None

    text = raw.strip()
    if not text:
        return None

    text = _TRAILING_YEAR_MARKERS.sub("", text).strip()
    text = text.replace(",", " ").replace(".", ".")

    if _ISO.match(text):
        try:
            return date.fromisoformat(text)
        except ValueError:
            return None

    # Translate non-English month tokens first; fuzzy=True would otherwise drop
    # them silently and pick whichever leftover digit looks like a month.
    substituted = _replace_months(text)
    candidates = [substituted] if substituted != text.lower() else [text]
    candidates.append(text)

    for cand in candidates:
        cand = re.sub(r"\s+", " ", cand).strip()
        if not cand:
            continue
        # Prefer day-first to match Uzbek/Russian conventions.
        try:
            parsed = du_parser.parse(cand, dayfirst=True, fuzzy=True)
            if 1900 <= parsed.year <= 2100:
                return parsed.date()
        except (du_parser.ParserError, ValueError, OverflowError):
            continue

    # Final fall-back for purely numeric strings of unusual separators.
    if _MMDDYY_NUMERIC.match(text):
        parts = re.split(r"[./\-\s]+", text)
        try:
            day, month, year = (int(p) for p in parts[:3])
            if year < 100:
                year += 2000 if year < 50 else 1900
            return date(year, month, day)
        except ValueError:
            return None

    return None


def parse_mrz_date(yymmdd: str) -> date | None:
    """Parse a YYMMDD MRZ date. Pivots two-digit years on a 50-year window."""
    if len(yymmdd) != 6 or not yymmdd.isdigit():
        return None
    yy, mm, dd = int(yymmdd[0:2]), int(yymmdd[2:4]), int(yymmdd[4:6])
    year = 2000 + yy if yy < 50 else 1900 + yy
    try:
        return date(year, mm, dd)
    except ValueError:
        return None
