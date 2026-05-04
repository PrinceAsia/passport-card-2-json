"""Tesseract OCR wrapper with optional EasyOCR fallback.

Tesseract is the primary engine; if its average word confidence falls below
`Settings.ocr_min_confidence`, the same image is re-OCR'd with EasyOCR (when
enabled) and the higher-confidence result is kept.

EasyOCR is imported lazily and cached at module level so we never pay the
~1.5 GB model load cost when the fallback is disabled.

We deliberately use *both* Tesseract endpoints:

- `image_to_string` for the text payload — it preserves newlines and paragraph
  structure that label/value parsers rely on.
- `image_to_data` for per-word confidence + bounding boxes (joining its tokens
  back with spaces would lose layout, so we don't use it for the text).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock
from typing import Any

import numpy as np
import pytesseract
from numpy.typing import NDArray

ImageArray = NDArray[Any]


@dataclass(frozen=True, slots=True)
class OcrResult:
    """Output of one OCR pass over a single image."""

    text: str
    avg_confidence: float
    engine: str
    word_boxes: list[dict[str, Any]] = field(default_factory=list)


class TesseractEngine:
    """Thin wrapper around `pytesseract` with confidence aggregation."""

    def __init__(self, command: str, langs: str, psm: int) -> None:
        if command:
            pytesseract.pytesseract.tesseract_cmd = command
        self._langs = langs
        self._config = f"--psm {psm}"

    def run(self, image: ImageArray) -> OcrResult:
        """OCR `image` with the configured languages.

        Returns:
            An `OcrResult` whose `text` preserves line breaks and whose
            `avg_confidence` is the mean Tesseract per-word confidence.
        """
        text = pytesseract.image_to_string(
            image, lang=self._langs, config=self._config
        )
        confs, boxes = _word_data(image, lang=self._langs, config=self._config)
        avg = float(np.mean(confs)) if confs else 0.0
        return OcrResult(text=text, avg_confidence=avg, engine="tesseract", word_boxes=boxes)

    def run_mrz_zone(self, image: ImageArray) -> str:
        """Run a dedicated OCR pass tuned for the MRZ alphabet.

        Restricting the character whitelist to `A-Z 0-9 <` and forcing
        English-only language data prevents the engine from interpreting MRZ
        glyphs as Cyrillic or punctuation, which is a common failure mode on
        Uzbek passports printed with both scripts.
        """
        config = (
            "--psm 6 -c "
            "tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789<"
        )
        return str(pytesseract.image_to_string(image, lang="eng", config=config))


def _word_data(
    image: ImageArray, *, lang: str, config: str
) -> tuple[list[float], list[dict[str, Any]]]:
    """Return per-word confidences and bounding boxes from `image_to_data`."""
    data = pytesseract.image_to_data(
        image, lang=lang, config=config, output_type=pytesseract.Output.DICT
    )
    confs: list[float] = []
    boxes: list[dict[str, Any]] = []
    for i, token in enumerate(data["text"]):
        if not token or not token.strip():
            continue
        try:
            conf = float(data["conf"][i])
        except (TypeError, ValueError):
            conf = -1.0
        if conf < 0:
            continue
        confs.append(conf)
        boxes.append(
            {
                "text": token,
                "conf": conf,
                "left": int(data["left"][i]),
                "top": int(data["top"][i]),
                "width": int(data["width"][i]),
                "height": int(data["height"][i]),
            }
        )
    return confs, boxes


_easyocr_reader: Any | None = None
_easyocr_lock = Lock()


def _get_easyocr_reader() -> Any:
    """Lazy-init a process-wide EasyOCR reader. Raises ImportError if the lib is absent."""
    global _easyocr_reader
    if _easyocr_reader is None:
        with _easyocr_lock:
            if _easyocr_reader is None:
                import easyocr  # noqa: PLC0415 — intentional lazy import

                _easyocr_reader = easyocr.Reader(["en", "ru"], gpu=False, verbose=False)
    return _easyocr_reader


class EasyOcrEngine:
    """Optional fallback wrapper around EasyOCR.

    EasyOCR doesn't ship Uzbek; it covers Russian + English which is enough
    for the visual fields of Uzbek documents (the MRZ is Latin/numeric only).
    """

    def run(self, image: ImageArray) -> OcrResult:
        """OCR `image` with EasyOCR and return text + average confidence."""
        reader = _get_easyocr_reader()
        results = reader.readtext(image, detail=1)
        # Sort by row then column so newline insertion approximates page layout.
        rows: list[tuple[int, int, str, float, list[int]]] = []
        for box, text, prob in results:
            if not text:
                continue
            xs = [int(p[0]) for p in box]
            ys = [int(p[1]) for p in box]
            rows.append((min(ys), min(xs), text, float(prob) * 100.0, [min(xs), min(ys), max(xs), max(ys)]))
        rows.sort()

        lines: list[list[str]] = []
        current_y = -1
        line_threshold = 12
        confs: list[float] = []
        boxes: list[dict[str, Any]] = []
        for y, _x, text, conf, b in rows:
            if not lines or abs(y - current_y) > line_threshold:
                lines.append([text])
                current_y = y
            else:
                lines[-1].append(text)
            confs.append(conf)
            boxes.append(
                {
                    "text": text,
                    "conf": conf,
                    "left": b[0],
                    "top": b[1],
                    "width": b[2] - b[0],
                    "height": b[3] - b[1],
                }
            )
        text = "\n".join(" ".join(line) for line in lines)
        avg = float(np.mean(confs)) if confs else 0.0
        return OcrResult(text=text, avg_confidence=avg, engine="easyocr", word_boxes=boxes)


@dataclass(frozen=True, slots=True)
class OcrPipelineResult:
    """Combined result of running primary + (optional) fallback OCR."""

    primary: OcrResult
    fallback: OcrResult | None
    chosen: OcrResult
    fallback_used: bool


class OcrPipeline:
    """Coordinates the primary engine and (optionally) the fallback engine."""

    def __init__(
        self,
        primary: TesseractEngine,
        *,
        fallback_enabled: bool,
        min_confidence: float,
    ) -> None:
        self._primary = primary
        self._fallback_enabled = fallback_enabled
        self._min_confidence = min_confidence

    @property
    def primary(self) -> TesseractEngine:
        """Expose the primary engine for ad-hoc passes (e.g. MRZ-zone OCR)."""
        return self._primary

    def run(self, image: ImageArray) -> OcrPipelineResult:
        """Run primary engine; optionally retry with fallback when confidence is low.

        Returns:
            An `OcrPipelineResult`. `chosen` is the higher-confidence run.
        """
        primary_result = self._primary.run(image)
        if (
            not self._fallback_enabled
            or primary_result.avg_confidence >= self._min_confidence
        ):
            return OcrPipelineResult(
                primary=primary_result,
                fallback=None,
                chosen=primary_result,
                fallback_used=False,
            )

        try:
            fallback_result = EasyOcrEngine().run(image)
        except ImportError:
            return OcrPipelineResult(
                primary=primary_result,
                fallback=None,
                chosen=primary_result,
                fallback_used=False,
            )

        chosen = (
            fallback_result
            if fallback_result.avg_confidence > primary_result.avg_confidence
            else primary_result
        )
        return OcrPipelineResult(
            primary=primary_result,
            fallback=fallback_result,
            chosen=chosen,
            fallback_used=chosen is fallback_result,
        )
