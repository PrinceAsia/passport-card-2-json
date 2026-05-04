"""POST /api/v1/documents/extract — main OCR endpoint."""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Depends, File, Form, Request, UploadFile

from app.api.dependencies import get_request_id, require_api_key
from app.config import get_settings
from app.exceptions import (
    FileTooLargeError,
    InvalidFileError,
    UnsupportedMediaTypeError,
)
from app.schemas.requests import DocumentTypeRequest
from app.schemas.responses import ExtractionResponse
from app.services.extraction import process_upload

router = APIRouter()
log = structlog.get_logger("api")

_ALLOWED_MIME = {"image/jpeg", "image/png", "image/webp", "application/pdf"}


@router.post(
    "/documents/extract",
    response_model=ExtractionResponse,
    summary="Extract structured data from an Uzbek identity document",
)
async def extract_document(
    request: Request,
    file: UploadFile = File(..., description="Image (JPG/PNG/WEBP) or PDF document."),
    document_type: DocumentTypeRequest = Form(default=DocumentTypeRequest.AUTO),
    language_hint: str = Form(default="uz,ru,en"),
    request_id: str = Depends(get_request_id),
    _: None = Depends(require_api_key),
) -> ExtractionResponse:
    """Validate input, run the OCR pipeline in a thread pool, return the response.

    Args:
        file: The uploaded image or PDF.
        document_type: Optional override; defaults to auto-detection.
        language_hint: Comma-separated language codes (uz, ru, en) for OCR.

    Returns:
        Fully populated `ExtractionResponse`.

    Raises:
        UnsupportedMediaTypeError: MIME type not in the allow-list.
        FileTooLargeError: Upload exceeds `MAX_FILE_SIZE_MB`.
        InvalidFileError: File cannot be decoded.
        OCREmptyResultError: OCR produced no text.
        DocumentNotRecognizedError: Classifier could not identify the layout.
    """
    settings = get_settings()
    started = time.perf_counter()

    if file.content_type not in _ALLOWED_MIME:
        raise UnsupportedMediaTypeError(
            f"MIME type '{file.content_type}' is not supported.",
            details={"allowed": sorted(_ALLOWED_MIME)},
        )

    payload = await file.read()
    size = len(payload)
    if size == 0:
        raise InvalidFileError("Uploaded file is empty.")
    if size > settings.max_file_size_bytes:
        raise FileTooLargeError(
            f"File exceeds the {settings.max_file_size_mb} MB limit.",
            details={"size_bytes": size, "limit_bytes": settings.max_file_size_bytes},
        )

    log.info(
        "extract.received",
        request_id=request_id,
        filename=file.filename,
        mime_type=file.content_type,
        size_bytes=size,
        document_type=document_type.value,
    )

    response = await asyncio.to_thread(
        process_upload,
        data=payload,
        filename=file.filename or "upload",
        mime_type=file.content_type or "application/octet-stream",
        document_type=document_type,
        language_hint=language_hint,
        request_id=request_id,
    )
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    response.processing_time_ms = elapsed_ms
    response.processed_at = datetime.now(UTC)

    log.info(
        "extract.completed",
        request_id=request_id,
        elapsed_ms=elapsed_ms,
        detected_type=response.document.detected_type,
        avg_confidence=response.ocr_metadata.avg_confidence,
    )
    return response
