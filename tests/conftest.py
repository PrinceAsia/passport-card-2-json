"""Shared pytest fixtures.

Tests run with OCR engines mocked at the import boundary (`TesseractEngine`)
so they don't require a system Tesseract install. Real OCR can be exercised
manually via `make dev` and curl.
"""

from __future__ import annotations

import io
from collections.abc import Iterator
from typing import Any
from unittest.mock import patch

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.core.ocr_engine import OcrPipelineResult, OcrResult


@pytest.fixture(autouse=True)
def _no_real_settings_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force a clean test config — disable auth, rate limit high enough to ignore."""
    monkeypatch.setenv("API_KEYS", "")
    monkeypatch.setenv("RATE_LIMIT", "1000/minute")
    monkeypatch.setenv("OCR_FALLBACK_ENABLED", "false")
    monkeypatch.setenv("ENABLE_METRICS", "false")
    # Reset the @lru_cache so the new env is picked up.
    from app.config import get_settings

    get_settings.cache_clear()


def _stub_pipeline_result(text: str, confidence: float = 95.0) -> OcrPipelineResult:
    primary = OcrResult(text=text, avg_confidence=confidence, engine="tesseract")
    return OcrPipelineResult(primary=primary, fallback=None, chosen=primary, fallback_used=False)


@pytest.fixture
def passport_text() -> str:
    """OCR-style raw text for a TD3 passport with a 44-char MRZ pair."""
    # Lines are exactly 44 chars per ICAO TD3 spec; check digits are placeholders.
    return (
        "REPUBLIC OF UZBEKISTAN PASSPORT\n"
        "Surname: KARIMOV\n"
        "Given names: ALISHER\n"
        "Nationality: UZB\n"
        "Date of birth: 12.05.1990\n"
        "Sex: M\n"
        "Date of issue: 01.01.2020\n"
        "Date of expiry: 01.01.2030\n"
        "Authority: MIA\n"
        "Personal number: 12345678901234\n"
        "P<UZBKARIMOV<<ALISHER<<<<<<<<<<<<<<<<<<<<<<<\n"
        "AA12345670UZB9005120M30010101234567890123400\n"
    )


@pytest.fixture
def id_card_text() -> str:
    """OCR-style raw text for a TD1 ID card with a 3-line MRZ."""
    return (
        "SHAXSIY GUVOHNOMA / ID CARD\n"
        "I<UZBAA1234567<<<<<<<<<<<<<<<<\n"
        "9005120M3001017UZB<<<<<<<<<<<8\n"
        "KARIMOV<<ALISHER<<<<<<<<<<<<<<\n"
    )


@pytest.fixture
def birth_cert_text() -> str:
    return (
        "TUG'ILGANLIK HAQIDA GUVOHNOMA\n"
        "Series: III-AB № 123456\n"
        "Familiya: KARIMOV\n"
        "Ismi: ALISHER\n"
        "Tug'ilgan sanasi: 12.05.2010\n"
        "Tug'ilgan joyi: Toshkent\n"
        "Otasi: KARIMOV ABDULLA\n"
        "Onasi: KARIMOVA NIGORA\n"
        "Berilgan: 15.05.2010\n"
    )


def _make_jpeg(size: tuple[int, int] = (400, 600)) -> bytes:
    """Return a tiny JPEG payload for upload tests."""
    img = Image.new("RGB", size, color=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=80)
    return buf.getvalue()


@pytest.fixture
def jpeg_bytes() -> bytes:
    return _make_jpeg()


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """Build a TestClient with the OCR pipeline patched out."""
    # Patch the pipeline.run to return deterministic text *only* if a test
    # explicitly sets `client.app.state._stub_text`. Default = empty.
    from app.main import create_app

    app = create_app()

    def _patched_run(self: Any, image: np.ndarray) -> OcrPipelineResult:  # noqa: ARG001
        text: str = getattr(app.state, "_stub_text", "")
        confidence: float = getattr(app.state, "_stub_confidence", 90.0)
        return _stub_pipeline_result(text, confidence=confidence)

    with (
        patch("app.core.ocr_engine.OcrPipeline.run", _patched_run),
        patch("app.services.extraction.parse_mrz_from_image", return_value=None),
        TestClient(app) as c,
    ):
        yield c
