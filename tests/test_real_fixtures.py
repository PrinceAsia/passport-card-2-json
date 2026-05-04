"""End-to-end OCR integration tests against real anonymized sample images.

Skipped automatically if the system Tesseract binary is missing — that lets the
unit suite run on CI without OCR dependencies. When Tesseract is present, these
tests run the full pipeline (no mocks) and assert the *minimum* set of fields
that should always extract from the bundled fixtures. They guard against
regressions in preprocessing, OCR text reconstruction, MRZ parsing, and the
label-positional extractors.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from app.config import get_settings
from app.schemas.requests import DocumentTypeRequest
from app.services.extraction import process_upload

FIXTURES = Path(__file__).parent / "fixtures"

pytestmark = pytest.mark.skipif(
    shutil.which("tesseract") is None,
    reason="System tesseract not available — skipping integration tests.",
)


def _run(filename: str, mime_type: str = "image/jpeg") -> dict[str, object]:
    """Execute the full pipeline on a fixture and return the fields dict."""
    get_settings.cache_clear()
    payload = (FIXTURES / filename).read_bytes()
    response = process_upload(
        data=payload,
        filename=filename,
        mime_type=mime_type,
        document_type=DocumentTypeRequest.AUTO,
        language_hint="uz,ru,en",
        request_id="test",
    )
    fields = response.document.fields.model_dump(mode="json")
    fields["_detected_type"] = response.document.detected_type
    return fields


def test_uzbek_old_passport_extracts_visual_fields() -> None:
    """Old-style Uzbek passport: visual labels in mixed Cyrillic/Latin scripts."""
    fields = _run("Uzbekistan_Pasport_(old).jpg")
    assert fields["_detected_type"] == "passport"
    assert fields["surname"] == "АХМЕДОВ"
    assert fields["given_names"] == "ШУХРАТ"
    assert fields["nationality"] == "ЎЗБЕК"
    assert fields["date_of_birth"] == "1984-06-16"
    assert fields["place_of_birth"] == "ТОШКЕНТ"
    assert fields["sex"] == "M"
    # Issue and expiry must differ — they live on the same OCR line.
    assert fields["date_of_issue"] != fields["date_of_expiry"]


def test_id_card_1_recovers_td3_mrz() -> None:
    """The bottom of this image has a TD3 MRZ that must be recovered."""
    fields = _run("ID_Card_1.png", mime_type="image/png")
    assert fields["surname"] == "TILLAHODJAEV"
    assert fields["given_names"] == "AKROMJON"
    assert fields["nationality"] == "UZB"
    assert fields["sex"] == "M"
    assert fields["date_of_birth"] == "1988-09-11"
    # MRZ may be slightly truncated, but the line must be populated.
    assert fields["mrz_line_1"] and fields["mrz_line_1"].startswith("P<UZB")
    assert fields["mrz_line_2"] and fields["mrz_line_2"].startswith("AA")


def test_id_card_2_extracts_visual_fields_without_mrz() -> None:
    """Modern ID card without a clean MRZ — must still extract via visual labels."""
    fields = _run("ID_Card_2.jpg")
    assert fields["_detected_type"] == "id_card"
    assert fields["surname"] == "IKRAMOV"
    assert fields["given_names"] == "AKROM"
    assert fields["nationality"] == "UZB"
    assert fields["sex"] == "M"
    assert fields["date_of_issue"] == "2019-12-05"
    assert fields["date_of_expiry"] == "2029-12-05"
    # PINFL: 14 digits canonical, OCR may add/drop one.
    assert fields["personal_number"] is not None
    assert 13 <= len(fields["personal_number"]) <= 15


def test_birth_certificate_extracts_series_and_registry() -> None:
    """Birth certificate OCR is noisy; only stable signals are asserted."""
    fields = _run("birth_cert_1.jpg")
    assert fields["_detected_type"] == "birth_certificate"
    assert fields["certificate_number"] == "0029340"
    # Registry office contains the FHDYO substring.
    assert fields["registry_office"] and "FHDYO" in fields["registry_office"]
