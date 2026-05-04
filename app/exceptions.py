"""Domain-specific exceptions and the error code catalogue.

Each exception maps cleanly to an HTTP status code in the API layer. Keep
`ErrorCode` values in sync with the README error table so clients can rely on them.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class ErrorCode(StrEnum):
    """Machine-readable error codes returned in the API error envelope."""

    UNSUPPORTED_MEDIA_TYPE = "UNSUPPORTED_MEDIA_TYPE"
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    INVALID_FILE = "INVALID_FILE"
    OCR_EMPTY_RESULT = "OCR_EMPTY_RESULT"
    DOCUMENT_NOT_RECOGNIZED = "DOCUMENT_NOT_RECOGNIZED"
    UNAUTHORIZED = "UNAUTHORIZED"
    RATE_LIMITED = "RATE_LIMITED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class OCRApiError(Exception):
    """Base class for all domain errors raised inside the OCR pipeline."""

    status_code: int = 500
    error_code: ErrorCode = ErrorCode.INTERNAL_ERROR

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class UnsupportedMediaTypeError(OCRApiError):
    """Raised when an unsupported MIME type is uploaded."""

    status_code = 415
    error_code = ErrorCode.UNSUPPORTED_MEDIA_TYPE


class FileTooLargeError(OCRApiError):
    """Raised when the uploaded file exceeds `MAX_FILE_SIZE_MB`."""

    status_code = 413
    error_code = ErrorCode.FILE_TOO_LARGE


class InvalidFileError(OCRApiError):
    """Raised when the uploaded file is corrupted or unreadable."""

    status_code = 400
    error_code = ErrorCode.INVALID_FILE


class OCREmptyResultError(OCRApiError):
    """Raised when OCR completes but produces no usable text."""

    status_code = 422
    error_code = ErrorCode.OCR_EMPTY_RESULT


class DocumentNotRecognizedError(OCRApiError):
    """Raised when no supported document layout could be detected."""

    status_code = 422
    error_code = ErrorCode.DOCUMENT_NOT_RECOGNIZED


class UnauthorizedError(OCRApiError):
    """Raised when an API key is missing or invalid."""

    status_code = 401
    error_code = ErrorCode.UNAUTHORIZED
