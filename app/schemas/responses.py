"""Response schemas returned by the API.

Every model uses `Field(..., description=...)` so the auto-generated OpenAPI docs
provide a useful contract to API consumers.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.exceptions import ErrorCode


class _Base(BaseModel):
    """Common config: forbid unknown fields server-side, but allow them on input."""

    model_config = ConfigDict(populate_by_name=True, str_strip_whitespace=True)


# --------------------------------------------------------------------------- #
# Document field models
# --------------------------------------------------------------------------- #


class _PassportLikeFields(_Base):
    """Fields shared between passport and ID card extractors."""

    document_number: str | None = Field(default=None, description="Document serial number, e.g. AA1234567.")
    surname: str | None = Field(default=None, description="Surname / last name as printed.")
    given_names: str | None = Field(default=None, description="Given names / first + middle.")
    nationality: str | None = Field(default=None, description="ISO 3166-1 alpha-3 nationality, e.g. UZB.")
    date_of_birth: date | None = Field(default=None, description="Date of birth (ISO 8601).")
    date_of_birth_raw: str | None = Field(default=None, description="Original DOB string if parsing failed.")
    sex: Literal["M", "F"] | None = Field(default=None, description="Sex marker.")
    place_of_birth: str | None = Field(default=None, description="Place of birth as printed.")
    date_of_issue: date | None = Field(default=None, description="Issue date (ISO 8601).")
    date_of_issue_raw: str | None = Field(default=None, description="Raw issue date if parsing failed.")
    date_of_expiry: date | None = Field(default=None, description="Expiry date (ISO 8601).")
    date_of_expiry_raw: str | None = Field(default=None, description="Raw expiry date if parsing failed.")
    issuing_authority: str | None = Field(default=None, description="Issuing authority text block.")
    personal_number: str | None = Field(default=None, description="14-digit JShShIR / PINFL.")
    mrz_line_1: str | None = Field(default=None, description="MRZ line 1 (raw).")
    mrz_line_2: str | None = Field(default=None, description="MRZ line 2 (raw).")
    mrz_line_3: str | None = Field(default=None, description="MRZ line 3, only for ID cards (TD1).")
    mrz_check_digits_valid: bool | None = Field(
        default=None,
        description="True if all MRZ check digits validate per ICAO 9303.",
    )


class PassportFields(_PassportLikeFields):
    """Extracted fields for a passport (TD3 MRZ, two lines)."""

    document_type: Literal["passport"] = Field(default="passport")


class IdCardFields(_PassportLikeFields):
    """Extracted fields for an Uzbek national ID card (TD1 MRZ, three lines)."""

    document_type: Literal["id_card"] = Field(default="id_card")


class BirthCertificateFields(_Base):
    """Extracted fields for an Uzbek birth certificate."""

    document_type: Literal["birth_certificate"] = Field(default="birth_certificate")
    certificate_series: str | None = Field(default=None, description="Series, e.g. 'III-AB'.")
    certificate_number: str | None = Field(default=None, description="Numeric certificate number.")
    child_surname: str | None = Field(default=None, description="Child's surname.")
    child_given_names: str | None = Field(default=None, description="Child's given names.")
    child_date_of_birth: date | None = Field(default=None, description="Child DOB (ISO 8601).")
    child_date_of_birth_raw: str | None = Field(default=None)
    child_place_of_birth: str | None = Field(default=None)
    child_sex: Literal["M", "F"] | None = Field(default=None)
    father_full_name: str | None = Field(default=None)
    father_nationality: str | None = Field(default=None)
    mother_full_name: str | None = Field(default=None)
    mother_nationality: str | None = Field(default=None)
    registry_office: str | None = Field(default=None)
    registration_number: str | None = Field(default=None)
    registration_date: date | None = Field(default=None)
    registration_date_raw: str | None = Field(default=None)
    date_of_issue: date | None = Field(default=None)
    date_of_issue_raw: str | None = Field(default=None)


# --------------------------------------------------------------------------- #
# Envelope models
# --------------------------------------------------------------------------- #


class InputBlock(_Base):
    """Echo of the validated input metadata."""

    filename: str = Field(..., description="Sanitized filename.")
    mime_type: str = Field(..., description="Validated MIME type.")
    size_bytes: int = Field(..., ge=0, description="Original file size in bytes.")
    page_count: int = Field(..., ge=1, description="Number of pages processed.")


class OcrMetadata(_Base):
    """Metadata describing how OCR was performed for this request."""

    engine_primary: str = Field(default="tesseract")
    engine_fallback_used: bool = Field(default=False)
    avg_confidence: float = Field(default=0.0, ge=0.0, le=100.0)
    low_confidence_fields: list[str] = Field(default_factory=list)


class DocumentBlock(_Base):
    """Detected document type plus extracted fields and raw OCR text."""

    detected_type: Literal["passport", "id_card", "birth_certificate", "unknown"] = Field(
        ..., description="Classifier output (or requested type if forced)."
    )
    detection_confidence: float = Field(..., ge=0.0, le=1.0)
    language_detected: list[str] = Field(default_factory=list)
    fields: PassportFields | IdCardFields | BirthCertificateFields | dict[str, Any] = Field(
        default_factory=dict, description="Typed fields per detected document type."
    )
    raw_text: str = Field(default="", description="Concatenated OCR text from all pages.")
    raw_text_per_page: list[str] = Field(default_factory=list)


class ExtractionResponse(_Base):
    """Top-level response returned by POST /api/v1/documents/extract."""

    success: bool = Field(default=True)
    request_id: str = Field(..., description="UUID v4 for log correlation.")
    processed_at: datetime = Field(..., description="UTC timestamp the response was sealed.")
    processing_time_ms: int = Field(..., ge=0)
    input: InputBlock
    document: DocumentBlock
    ocr_metadata: OcrMetadata
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class ErrorResponse(_Base):
    """Uniform error envelope."""

    success: Literal[False] = False
    request_id: str
    error_code: ErrorCode
    message: str
    details: dict[str, Any] | None = None


class SupportedDocumentInfo(_Base):
    """Metadata describing one supported document type."""

    document_type: Literal["passport", "id_card", "birth_certificate"]
    description: str
    fields: list[str]


class SupportedDocumentsResponse(_Base):
    """Response of GET /api/v1/supported-documents."""

    documents: list[SupportedDocumentInfo]
