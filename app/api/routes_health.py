"""Liveness, supported-document, and metadata endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from app.schemas.responses import (
    BirthCertificateFields,
    IdCardFields,
    PassportFields,
    SupportedDocumentInfo,
    SupportedDocumentsResponse,
)

router = APIRouter()


@router.get("/health", summary="Liveness probe")
async def health() -> dict[str, str]:
    """Liveness check — always returns `{"status": "ok"}` if the app is up."""
    return {"status": "ok"}


@router.get(
    "/supported-documents",
    response_model=SupportedDocumentsResponse,
    summary="List supported document types and their fields",
)
async def supported_documents() -> SupportedDocumentsResponse:
    """Return a manifest of supported document types and the fields each provides."""
    return SupportedDocumentsResponse(
        documents=[
            SupportedDocumentInfo(
                document_type="passport",
                description="Uzbek international passport (TD3 MRZ).",
                fields=list(PassportFields.model_fields.keys()),
            ),
            SupportedDocumentInfo(
                document_type="id_card",
                description="Uzbek national ID card / shaxsiy guvohnoma (TD1 MRZ).",
                fields=list(IdCardFields.model_fields.keys()),
            ),
            SupportedDocumentInfo(
                document_type="birth_certificate",
                description="Uzbek birth certificate / tug'ilganlik haqida guvohnoma.",
                fields=list(BirthCertificateFields.model_fields.keys()),
            ),
        ]
    )
