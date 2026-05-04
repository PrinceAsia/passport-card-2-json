"""Synchronous orchestration of the full OCR pipeline.

Called from the API layer via `asyncio.to_thread` so heavy OpenCV/Tesseract work
never blocks the event loop. The function is designed to be a pure function of
its inputs — no global mutable state, no disk persistence (PDF rendering is
in-memory via PyMuPDF).
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any, cast

import structlog
from numpy.typing import NDArray

from app.config import get_settings
from app.core.document_classifier import DocType, classify_document
from app.core.mrz_parser import (
    MrzResult,
    best_mrz,
    parse_mrz_from_image,
    parse_mrz_from_text,
)
from app.core.ocr_engine import OcrPipeline, TesseractEngine
from app.core.preprocessing import PreprocessConfig, pil_from_bytes, preprocess, to_numpy_rgb
from app.exceptions import (
    DocumentNotRecognizedError,
    InvalidFileError,
    OCREmptyResultError,
)
from app.extractors import (
    BaseExtractor,
    BirthCertificateExtractor,
    ExtractionContext,
    IdCardExtractor,
    PassportExtractor,
)
from app.schemas.requests import DocumentTypeRequest
from app.schemas.responses import (
    DocumentBlock,
    ExtractionResponse,
    InputBlock,
    OcrMetadata,
)
from app.utils.pdf_utils import pdf_bytes_to_images
from app.utils.text_normalize import clean_ocr_text, detect_languages, sanitize_filename

log = structlog.get_logger("extraction")


def _build_pipeline() -> OcrPipeline:
    """Build the OCR pipeline once per call (engines are cheap to construct)."""
    settings = get_settings()
    primary = TesseractEngine(
        command=settings.tesseract_cmd,
        langs=settings.tesseract_langs,
        psm=settings.tesseract_psm,
    )
    return OcrPipeline(
        primary,
        fallback_enabled=settings.ocr_fallback_enabled,
        min_confidence=settings.ocr_min_confidence,
    )


def _build_preprocess_config() -> PreprocessConfig:
    s = get_settings()
    return PreprocessConfig(
        auto_orient=s.preprocess_auto_orient,
        deskew=s.preprocess_deskew,
        grayscale=s.preprocess_grayscale,
        threshold=s.preprocess_threshold,
        denoise=s.preprocess_denoise,
        perspective_warp=s.preprocess_perspective_warp,
    )


def _crop_mrz_zone(image: NDArray[Any]) -> NDArray[Any] | None:
    """Return the bottom strip of `image` (where the MRZ lives) or None.

    Returns None for tiny images where the crop wouldn't help.
    """
    if image is None or image.size == 0:
        return None
    h = image.shape[0]
    if h < 200:
        return None
    # Bottom 30% is enough to capture both TD3 (2 lines) and TD1 (3 lines).
    cropped: NDArray[Any] = image[int(h * 0.7) :]
    return cropped


def _decode_pages(data: bytes, mime_type: str) -> list[NDArray[Any]]:
    """Decode the upload into a list of RGB NumPy pages.

    Raises:
        InvalidFileError: For unreadable bytes.
    """
    settings = get_settings()
    if mime_type == "application/pdf":
        return pdf_bytes_to_images(
            data, dpi=settings.pdf_dpi, max_pages=settings.pdf_max_pages
        )

    try:
        pil = pil_from_bytes(data)
    except ValueError as exc:
        raise InvalidFileError(str(exc)) from exc
    return [to_numpy_rgb(pil, auto_orient=settings.preprocess_auto_orient)]


def _select_extractor(detected_type: str) -> BaseExtractor:
    """Map a classifier label to an extractor instance."""
    if detected_type == "passport":
        return PassportExtractor()
    if detected_type == "id_card":
        return IdCardExtractor()
    if detected_type == "birth_certificate":
        return BirthCertificateExtractor()
    raise DocumentNotRecognizedError("No supported document layout matched the input.")


def process_upload(
    *,
    data: bytes,
    filename: str,
    mime_type: str,
    document_type: DocumentTypeRequest,
    language_hint: str,
    request_id: str,
) -> ExtractionResponse:
    """End-to-end pipeline. Decodes, preprocesses, OCRs, classifies, extracts.

    Args:
        data: Raw uploaded bytes.
        filename: Original (will be sanitized for echo).
        mime_type: Validated MIME type.
        document_type: Either an explicit override or `AUTO`.
        language_hint: Currently informational — Tesseract uses configured langs.
        request_id: Per-request UUID for log correlation.

    Returns:
        A fully-populated `ExtractionResponse`. `processing_time_ms` is set by
        the caller for tighter accuracy.

    Raises:
        InvalidFileError, OCREmptyResultError, DocumentNotRecognizedError.
    """
    started = time.perf_counter()
    pages = _decode_pages(data, mime_type)
    pp_config = _build_preprocess_config()
    pipeline = _build_pipeline()

    raw_per_page: list[str] = []
    confidences: list[float] = []
    fallback_used = False
    word_boxes: list[dict[str, object]] = []
    mrz_candidates: list[MrzResult | None] = []

    for original_page in pages:
        # Run PassportEye on the *original* page where possible (cleaner texture).
        mrz_candidates.append(parse_mrz_from_image(original_page))

        processed = preprocess(original_page, pp_config)
        result = pipeline.run(processed)
        raw_per_page.append(clean_ocr_text(result.chosen.text))
        confidences.append(result.chosen.avg_confidence)
        word_boxes.extend(result.chosen.word_boxes)
        fallback_used = fallback_used or result.fallback_used

        # Dedicated MRZ-zone pass: crop the bottom strip and OCR it with a
        # Latin-only whitelist. This recovers MRZs even when full-page OCR
        # mis-reads them as Cyrillic (common on dual-script Uzbek passports).
        mrz_zone = _crop_mrz_zone(original_page)
        if mrz_zone is not None:
            mrz_text = pipeline.primary.run_mrz_zone(mrz_zone)
            mrz_candidates.append(parse_mrz_from_text(mrz_text))

    raw_text = "\n\n".join(p for p in raw_per_page if p)
    if not raw_text.strip():
        raise OCREmptyResultError(
            "OCR engines returned no usable text.",
            details={"pages": len(pages)},
        )

    # Try MRZ again from concatenated text in case PassportEye missed it.
    mrz_candidates.append(parse_mrz_from_text(raw_text))
    mrz = best_mrz(*mrz_candidates)

    if document_type == DocumentTypeRequest.AUTO:
        cls = classify_document(raw_text, mrz)
        detected_type: DocType = cls.document_type
        detection_confidence = cls.confidence
    else:
        detected_type = cast(DocType, document_type.value)
        detection_confidence = 1.0

    if detected_type == "unknown":
        raise DocumentNotRecognizedError(
            "Could not identify a supported document layout.",
            details={"avg_confidence": sum(confidences) / max(len(confidences), 1)},
        )

    extractor = _select_extractor(detected_type)
    ctx = ExtractionContext(
        raw_text=raw_text,
        raw_text_per_page=raw_per_page,
        word_boxes=word_boxes,
        mrz=mrz,
    )
    fields_model, low_conf = extractor.extract(ctx)

    avg_conf = sum(confidences) / max(len(confidences), 1)
    elapsed_ms = int((time.perf_counter() - started) * 1000)

    log.debug(
        "extract.summary",
        request_id=request_id,
        page_count=len(pages),
        engine_fallback_used=fallback_used,
        avg_confidence=round(avg_conf, 2),
    )

    return ExtractionResponse(
        request_id=request_id,
        processed_at=datetime.now(UTC),
        processing_time_ms=elapsed_ms,
        input=InputBlock(
            filename=sanitize_filename(filename),
            mime_type=mime_type,
            size_bytes=len(data),
            page_count=len(pages),
        ),
        document=DocumentBlock(
            detected_type=detected_type,
            detection_confidence=detection_confidence,
            language_detected=detect_languages(raw_text) or [
                lang.strip() for lang in language_hint.split(",") if lang.strip()
            ],
            fields=fields_model,
            raw_text=raw_text,
            raw_text_per_page=raw_per_page,
        ),
        ocr_metadata=OcrMetadata(
            engine_primary="tesseract",
            engine_fallback_used=fallback_used,
            avg_confidence=round(avg_conf, 2),
            low_confidence_fields=low_conf,
        ),
    )
