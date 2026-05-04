"""Pydantic request and response schemas."""

from app.schemas.requests import DocumentTypeRequest
from app.schemas.responses import (
    BirthCertificateFields,
    DocumentBlock,
    ErrorResponse,
    ExtractionResponse,
    IdCardFields,
    InputBlock,
    OcrMetadata,
    PassportFields,
    SupportedDocumentInfo,
    SupportedDocumentsResponse,
)

__all__ = [
    "BirthCertificateFields",
    "DocumentBlock",
    "DocumentTypeRequest",
    "ErrorResponse",
    "ExtractionResponse",
    "IdCardFields",
    "InputBlock",
    "OcrMetadata",
    "PassportFields",
    "SupportedDocumentInfo",
    "SupportedDocumentsResponse",
]
