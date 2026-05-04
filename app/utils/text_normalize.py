"""Text normalization helpers for messy OCR output.

Tesseract often confuses Uzbek Latin apostrophes (`ʻ` U+02BB and `'` U+2019)
with ASCII `'`, and emits stray newlines / multiple spaces. The helpers here
canonicalize text so downstream regexes are simpler.
"""

from __future__ import annotations

import re
import unicodedata

_APOSTROPHES = {"ʻ", "‘", "’", "ʼ", "`", "´"}
_DASHES = {"‐", "‑", "‒", "–", "—", "―"}

_WHITESPACE_RE = re.compile(r"[ \t ]+")
_MULTI_NEWLINE_RE = re.compile(r"\n{3,}")


def normalize_apostrophes(text: str) -> str:
    """Replace assorted apostrophe-like glyphs with the ASCII single quote."""
    return "".join("'" if ch in _APOSTROPHES else ch for ch in text)


def normalize_dashes(text: str) -> str:
    """Replace fancy dashes (en/em/figure) with the ASCII hyphen."""
    return "".join("-" if ch in _DASHES else ch for ch in text)


def collapse_whitespace(text: str) -> str:
    """Collapse runs of horizontal whitespace and limit to two consecutive newlines."""
    text = _WHITESPACE_RE.sub(" ", text)
    text = _MULTI_NEWLINE_RE.sub("\n\n", text)
    return text.strip()


def clean_ocr_text(text: str) -> str:
    """Apply the full normalization pipeline to a raw OCR string."""
    text = unicodedata.normalize("NFKC", text)
    text = normalize_apostrophes(text)
    text = normalize_dashes(text)
    text = collapse_whitespace(text)
    return text


def sanitize_filename(name: str) -> str:
    """Return a filesystem-safe version of `name`.

    The original filename is never used as a disk path, but it is echoed in the
    response and logs — so we strip path separators, control characters, and
    cap the length.
    """
    name = name.replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(ch for ch in name if ch.isprintable())
    name = re.sub(r"[^\w\.\-]", "_", name)
    return name[:255] or "upload"


def detect_languages(text: str) -> list[str]:
    """Heuristically detect uz/ru/en presence in `text` based on character ranges."""
    languages: list[str] = []
    cyrillic = any("Ѐ" <= ch <= "ӿ" for ch in text)
    latin = any("a" <= ch.lower() <= "z" for ch in text)
    if cyrillic:
        languages.append("ru")
    if latin:
        # Treat Latin script as both Uzbek-Latin and English; the OCR set covers both.
        languages.extend(["uz", "en"])
    return languages
