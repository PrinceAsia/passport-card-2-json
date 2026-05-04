"""MRZ (Machine-Readable Zone) parsing per ICAO Doc 9303.

Two parsing paths run in parallel for resilience:

1. `passporteye` — full-image MRZ detector + OCR (most accurate when the
   visual zone is clean, but can miss heavily noisy scans).
2. Custom regex over Tesseract-extracted text — picks up MRZ lines even when
   PassportEye fails, e.g. in a multi-page PDF where the MRZ is on page 2.

The result is reconciled into a single `MrzResult`, choosing the path with the
highest check-digit validity score.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import date
from io import BytesIO
from typing import Any, Literal

from numpy.typing import NDArray
from PIL import Image

from app.utils.date_parser import parse_mrz_date

MrzFormat = Literal["TD1", "TD3", "unknown"]

# ICAO 9303 MRZ alphabet uses < as filler. We accept lines slightly longer than
# the canonical length and trim — OCR often appends stray characters or repeats
# fillers. The rest is filtered out by check-digit validation downstream.
_TD3_LINE_RE = re.compile(r"^[A-Z<0-9]{40,52}$")
_TD1_LINE_RE = re.compile(r"^[A-Z<0-9]{28,36}$")

# Map common OCR confusions to canonical MRZ chars.
# Replacements for OCR misreads of the filler character `<`. We deliberately do
# NOT remap `O→0` or `Q→0` because the surname/given-name positions contain
# real letters that would be corrupted.
#
# We also remap visually-identical Cyrillic letters to their Latin twins. On
# dual-script Uzbek passports Tesseract regularly classifies the MRZ glyphs
# as Cyrillic (А, В, Е, К, М, Н, О, Р, С, Т, Х, У) when they are in fact the
# Latin letters that ICAO 9303 mandates. Without this mapping, perfectly
# readable MRZ lines fail the `[A-Z<0-9]` regex and get discarded.
_MRZ_CHAR_MAP = str.maketrans(
    {
        # Filler glyphs.
        "«": "<", "‹": "<", "»": "<", "›": "<",
        "“": "<", "”": "<", "‘": "<", "’": "<",
        "—": "<", "–": "<", "·": "<", "*": "<",
        " ": "", "\t": "",
        # Cyrillic → Latin homoglyphs (uppercase).
        "А": "A", "В": "B", "Е": "E", "К": "K", "М": "M", "Н": "H",
        "О": "O", "Р": "P", "С": "C", "Т": "T", "Х": "X", "У": "Y",
        "І": "I", "Ј": "J",
    }
)


@dataclass(frozen=True, slots=True)
class MrzResult:
    """Parsed MRZ output with reliability flags."""

    format: MrzFormat
    raw_lines: list[str]
    document_number: str | None = None
    surname: str | None = None
    given_names: str | None = None
    nationality: str | None = None
    date_of_birth: date | None = None
    date_of_expiry: date | None = None
    sex: Literal["M", "F"] | None = None
    personal_number: str | None = None
    check_digits_valid: bool = False


# --------------------------------------------------------------------------- #
# Check-digit logic
# --------------------------------------------------------------------------- #


def _char_value(ch: str) -> int:
    """Return the ICAO 9303 numeric value of a single MRZ character."""
    if ch == "<":
        return 0
    if ch.isdigit():
        return int(ch)
    if ch.isalpha():
        return ord(ch.upper()) - 55
    return 0


def compute_check_digit(field: str) -> int:
    """Compute the ICAO 9303 check digit for `field` using weights 7-3-1."""
    weights = (7, 3, 1)
    total = sum(_char_value(ch) * weights[i % 3] for i, ch in enumerate(field))
    return total % 10


def _validate_digit(field: str, expected: str) -> bool:
    """Return True iff `expected` matches the computed check digit of `field`."""
    if not expected.isdigit():
        return False
    return compute_check_digit(field) == int(expected)


# --------------------------------------------------------------------------- #
# Name decoding helper
# --------------------------------------------------------------------------- #


def _split_names(name_field: str) -> tuple[str, str]:
    """Split an MRZ name field into (surname, given_names) using `<<`."""
    surname, _, rest = name_field.partition("<<")
    surname = surname.replace("<", " ").strip()
    given = rest.replace("<", " ").strip()
    return surname, given


# --------------------------------------------------------------------------- #
# Format-specific parsers
# --------------------------------------------------------------------------- #


def parse_td3(line1: str, line2: str) -> MrzResult:
    """Parse a TD3 (passport) MRZ — two lines of 44 characters each."""
    if len(line1) != 44 or len(line2) != 44:
        return MrzResult(format="TD3", raw_lines=[line1, line2])

    nationality = line2[10:13].replace("<", "")
    doc_number_raw = line2[0:9]
    doc_number = doc_number_raw.replace("<", "")
    dob_raw = line2[13:19]
    sex_raw = line2[20]
    expiry_raw = line2[21:27]
    personal_raw = line2[28:42].replace("<", "")

    surname, given = _split_names(line1[5:])

    checks_ok = all(
        [
            _validate_digit(doc_number_raw, line2[9]),
            _validate_digit(dob_raw, line2[19]),
            _validate_digit(expiry_raw, line2[27]),
        ]
    )

    sex: Literal["M", "F"] | None
    if sex_raw == "M":
        sex = "M"
    elif sex_raw == "F":
        sex = "F"
    else:
        sex = None

    return MrzResult(
        format="TD3",
        raw_lines=[line1, line2],
        document_number=doc_number or None,
        surname=surname or None,
        given_names=given or None,
        nationality=nationality or None,
        date_of_birth=parse_mrz_date(dob_raw),
        date_of_expiry=parse_mrz_date(expiry_raw),
        sex=sex,
        personal_number=personal_raw or None,
        check_digits_valid=checks_ok,
    )


def parse_td1(line1: str, line2: str, line3: str) -> MrzResult:
    """Parse a TD1 (national ID card) MRZ — three lines of 30 characters."""
    if len(line1) != 30 or len(line2) != 30 or len(line3) != 30:
        return MrzResult(format="TD1", raw_lines=[line1, line2, line3])

    doc_number_raw = line1[5:14]
    doc_number = doc_number_raw.replace("<", "")
    optional_data = line1[15:30].replace("<", "")
    dob_raw = line2[0:6]
    sex_raw = line2[7]
    expiry_raw = line2[8:14]
    nationality = line2[15:18].replace("<", "")
    surname, given = _split_names(line3)

    checks_ok = all(
        [
            _validate_digit(doc_number_raw, line1[14]),
            _validate_digit(dob_raw, line2[6]),
            _validate_digit(expiry_raw, line2[14]),
        ]
    )

    sex: Literal["M", "F"] | None
    if sex_raw == "M":
        sex = "M"
    elif sex_raw == "F":
        sex = "F"
    else:
        sex = None

    return MrzResult(
        format="TD1",
        raw_lines=[line1, line2, line3],
        document_number=doc_number or None,
        surname=surname or None,
        given_names=given or None,
        nationality=nationality or None,
        date_of_birth=parse_mrz_date(dob_raw),
        date_of_expiry=parse_mrz_date(expiry_raw),
        sex=sex,
        personal_number=optional_data or None,
        check_digits_valid=checks_ok,
    )


# --------------------------------------------------------------------------- #
# Driver functions
# --------------------------------------------------------------------------- #


def _normalize_mrz_line(raw: str) -> str:
    """Uppercase + remap filler glyphs + drop whitespace."""
    return raw.upper().translate(_MRZ_CHAR_MAP)


def _candidate_lines(text: str) -> list[str]:
    """Return uppercase, MRZ-shaped lines extracted from arbitrary OCR text."""
    out: list[str] = []
    for raw in text.splitlines():
        line = _normalize_mrz_line(raw.strip())
        if _TD3_LINE_RE.match(line) or _TD1_LINE_RE.match(line):
            out.append(line)
    return out


def _trim_to_length(line: str, target: int) -> str:
    """Truncate `line` to `target` chars, preferring to drop trailing fillers."""
    if len(line) <= target:
        return line
    # Strip trailing fillers first, then truncate.
    stripped = line.rstrip("<")
    if len(stripped) <= target:
        return stripped + "<" * (target - len(stripped))
    return line[:target]


def _classify_lines(lines: list[str]) -> list[str]:
    """Bucket lines as TD1 (30) or TD3 (44) by their normalized length."""
    return [_trim_to_length(line, 30 if len(line) <= 36 else 44) for line in lines]


def parse_mrz_from_text(text: str) -> MrzResult | None:
    """Try to parse MRZ from raw OCR text by regex-matching candidate lines.

    The lines may arrive in any order from OCR (TD3 line 1 starts with `P<`,
    TD3 line 2 starts with letters/digits), so we identify each role by its
    leading characters rather than position.

    Returns the strongest TD1 or TD3 candidate found, or None if the text
    contains no plausible MRZ.
    """
    raw_lines = _candidate_lines(text)
    lines = _classify_lines(raw_lines)
    td3 = [line for line in lines if len(line) == 44]
    td1 = [line for line in lines if len(line) == 30]

    if len(td3) >= 2:
        # TD3 line 1 begins with the document class indicator (typically `P`).
        line1 = next((line for line in td3 if line.startswith("P")), None)
        line2 = next((line for line in td3 if line is not line1), None)
        if line1 is None or line2 is None:
            line1, line2 = td3[0], td3[1]
        return parse_td3(line1, line2)

    if len(td1) >= 3:
        # TD1 line 3 holds the name field — heavy on letters and `<`, no
        # leading digit. Lines 1 and 2 typically start with a letter+digit.
        name_line = max(td1, key=lambda line: line.count("<") + sum(1 for ch in line if ch.isalpha()))
        rest = [line for line in td1 if line is not name_line]
        if len(rest) >= 2:
            return parse_td1(rest[0], rest[1], name_line)

    return None


def parse_mrz_from_image(image: NDArray[Any]) -> MrzResult | None:
    """Try to parse MRZ directly from `image` using PassportEye.

    PassportEye does its own crop + OCR; we only call this when image bytes
    are available (typically the original photo, not the preprocessed version).
    Returns None if PassportEye is unavailable or finds no MRZ.
    """
    try:
        from passporteye import read_mrz  # noqa: PLC0415
    except ImportError:
        return None

    try:
        pil = Image.fromarray(image)
        buf = BytesIO()
        pil.save(buf, format="PNG")
        buf.seek(0)
        mrz = read_mrz(buf, save_roi=False)
    except Exception:
        return None

    if mrz is None:
        return None

    data: dict[str, Any] = mrz.to_dict()
    raw_text: str = data.get("raw_text", "") or ""
    lines = [line for line in raw_text.splitlines() if line.strip()]
    parsed = parse_mrz_from_text("\n".join(lines))
    if parsed is not None:
        return parsed
    return None


def best_mrz(*candidates: MrzResult | None) -> MrzResult | None:
    """Pick the most reliable result from multiple parse attempts.

    Priority: validates check digits > more populated fields > first non-None.
    """
    valid = [c for c in candidates if c is not None]
    if not valid:
        return None
    valid.sort(
        key=lambda r: (r.check_digits_valid, sum(1 for v in asdict(r).values() if v)),
        reverse=True,
    )
    return valid[0]
