"""PDF helpers — render pages to NumPy images using PyMuPDF (fitz).

We deliberately avoid `pdf2image`/poppler because PyMuPDF ships as a single
wheel, has no external system dependency, and is significantly faster on the
small documents we process.
"""

from __future__ import annotations

import io
from typing import Any

import fitz
import numpy as np
from numpy.typing import NDArray
from PIL import Image

from app.exceptions import InvalidFileError

ImageArray = NDArray[Any]


def pdf_bytes_to_images(
    data: bytes,
    *,
    dpi: int = 300,
    max_pages: int = 10,
) -> list[ImageArray]:
    """Render a PDF (in memory) into a list of RGB NumPy arrays.

    Args:
        data: Raw PDF bytes.
        dpi: Render resolution. 300 is the documented goal; lower for speed.
        max_pages: Hard cap on pages processed to bound memory + time.

    Returns:
        A list of HxWx3 uint8 arrays — one per page, in document order.

    Raises:
        InvalidFileError: If the bytes don't represent a readable PDF.
    """
    if not data:
        raise InvalidFileError("Empty PDF payload.")

    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception as exc:  # fitz raises a generic RuntimeError on bad input
        raise InvalidFileError(f"Cannot open PDF: {exc}") from exc

    images: list[ImageArray] = []
    try:
        page_count = min(doc.page_count, max_pages)
        zoom = dpi / 72.0  # PDF default is 72 DPI; matrix scales accordingly.
        matrix = fitz.Matrix(zoom, zoom)
        for page_idx in range(page_count):
            page = doc.load_page(page_idx)
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            img = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")
            images.append(np.array(img))
    finally:
        doc.close()

    if not images:
        raise InvalidFileError("PDF has no renderable pages.")

    return images


def pdf_page_count(data: bytes) -> int:
    """Return the number of pages in a PDF without rendering them."""
    try:
        with fitz.open(stream=data, filetype="pdf") as doc:
            return int(doc.page_count)
    except Exception as exc:
        raise InvalidFileError(f"Cannot read PDF: {exc}") from exc
