"""OpenCV-based image preprocessing pipeline.

The pipeline is composed of independently toggleable steps so it can be tuned
from `Settings` without code changes. The order matches the spec:

    EXIF orient → deskew → grayscale → threshold → denoise → perspective warp
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np
from numpy.typing import NDArray
from PIL import Image, ImageOps

ImageArray = NDArray[Any]


@dataclass(frozen=True, slots=True)
class PreprocessConfig:
    """Toggle each preprocessing step on or off independently."""

    auto_orient: bool = True
    deskew: bool = True
    grayscale: bool = True
    threshold: bool = True
    denoise: bool = True
    perspective_warp: bool = True


def pil_from_bytes(data: bytes) -> Image.Image:
    """Open raw image bytes as a PIL `Image`, honoring EXIF orientation.

    Raises:
        ValueError: if the bytes can't be decoded as an image.
    """
    import io

    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception as exc:
        raise ValueError(f"Cannot decode image: {exc}") from exc
    return img


def to_numpy_rgb(img: Image.Image, *, auto_orient: bool = True) -> ImageArray:
    """Convert a PIL image to an RGB NumPy array, optionally applying EXIF orientation."""
    if auto_orient:
        img = ImageOps.exif_transpose(img)
    img = img.convert("RGB")
    return np.array(img, dtype=np.uint8)


def deskew(image: ImageArray) -> ImageArray:
    """Estimate the rotation angle from text contours and rotate the image flat.

    Falls back to the identity transform if no usable angle is found — we'd
    rather feed Tesseract a slightly skewed image than a wildly mis-rotated one.
    """
    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY) if image.ndim == 3 else image
    inv = cv2.bitwise_not(gray)
    thresh = cv2.threshold(inv, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)[1]
    coords = np.column_stack(np.where(thresh > 0))
    if coords.size < 200:
        return image

    angle = cv2.minAreaRect(coords)[-1]
    # cv2 returns angles in [-90, 0); normalize to small rotations only.
    angle = -(90 + angle) if angle < -45 else -angle

    if abs(angle) < 0.5 or abs(angle) > 30:
        return image  # noisy estimate — skip.

    h, w = image.shape[:2]
    matrix = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    return cv2.warpAffine(
        image,
        matrix,
        (w, h),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE,
    )


def to_grayscale(image: ImageArray) -> ImageArray:
    """Convert to single-channel grayscale (no-op if already 2-D)."""
    if image.ndim == 2:
        return image
    return cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)


def adaptive_threshold(image: ImageArray) -> ImageArray:
    """Apply Otsu thresholding for high-contrast bi-level output."""
    gray = to_grayscale(image)
    _, binarized = cv2.threshold(
        gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
    )
    return binarized


def denoise(image: ImageArray) -> ImageArray:
    """Light non-local-means denoising. Cheap on small images."""
    if image.ndim == 2:
        return cv2.fastNlMeansDenoising(image, h=10, templateWindowSize=7, searchWindowSize=21)
    return cv2.fastNlMeansDenoisingColored(image, h=10, hColor=10)


def _largest_quad_contour(image: ImageArray) -> ImageArray | None:
    """Find the largest 4-corner contour in the image, if one is dominant."""
    gray = to_grayscale(image)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 75, 200)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    contours = sorted(contours, key=cv2.contourArea, reverse=True)[:5]
    img_area = image.shape[0] * image.shape[1]
    for c in contours:
        peri = cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, 0.02 * peri, True)
        if len(approx) == 4 and cv2.contourArea(approx) > 0.2 * img_area:
            return approx.reshape(4, 2)
    return None


def _order_points(pts: ImageArray) -> ImageArray:
    """Order 4 points as TL, TR, BR, BL for warp-perspective."""
    rect = np.zeros((4, 2), dtype="float32")
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]
    rect[2] = pts[np.argmax(s)]
    diff = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(diff)]
    rect[3] = pts[np.argmax(diff)]
    return rect


def perspective_warp(image: ImageArray) -> ImageArray:
    """If a clear quadrilateral is detected, warp the document to a flat rectangle.

    Only triggers when the document occupies less than ~80% of the frame —
    otherwise the photo is essentially already a clean scan.
    """
    img_area = image.shape[0] * image.shape[1]
    quad = _largest_quad_contour(image)
    if quad is None:
        return image
    quad_area = cv2.contourArea(quad.reshape(-1, 1, 2).astype(np.float32))
    if quad_area >= 0.8 * img_area:
        return image

    rect = _order_points(quad.astype("float32"))
    (tl, tr, br, bl) = rect
    width_a = np.linalg.norm(br - bl)
    width_b = np.linalg.norm(tr - tl)
    height_a = np.linalg.norm(tr - br)
    height_b = np.linalg.norm(tl - bl)
    max_w = int(max(width_a, width_b))
    max_h = int(max(height_a, height_b))
    if max_w < 100 or max_h < 100:
        return image

    dst = np.array(
        [[0, 0], [max_w - 1, 0], [max_w - 1, max_h - 1], [0, max_h - 1]],
        dtype="float32",
    )
    matrix = cv2.getPerspectiveTransform(rect, dst)
    return cv2.warpPerspective(image, matrix, (max_w, max_h))


def preprocess(image: ImageArray, config: PreprocessConfig) -> ImageArray:
    """Run the full preprocessing pipeline according to the toggles in `config`.

    Args:
        image: HxW or HxWx3 uint8 array (RGB if 3-channel).
        config: Step toggles.

    Returns:
        A processed 2-D or 3-D uint8 array ready for OCR.
    """
    out = image
    if config.perspective_warp:
        out = perspective_warp(out)
    if config.deskew:
        out = deskew(out)
    if config.grayscale:
        out = to_grayscale(out)
    if config.denoise:
        out = denoise(out)
    if config.threshold:
        out = adaptive_threshold(out)
    return out
