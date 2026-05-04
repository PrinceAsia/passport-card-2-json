"""ID-card (TD1 MRZ) field extractor.

Reuses the passport extractor by composition (not inheritance) so the return
type can be `IdCardFields` without a Liskov violation.
"""

from __future__ import annotations

from app.extractors.base import BaseExtractor, ExtractionContext
from app.extractors.passport import PassportExtractor
from app.schemas.responses import IdCardFields


class IdCardExtractor(BaseExtractor):
    """ID-card extractor — same logic as passport with three-line MRZ."""

    def __init__(self) -> None:
        self._passport = PassportExtractor()

    def extract(self, ctx: ExtractionContext) -> tuple[IdCardFields, list[str]]:
        """Return parsed `IdCardFields` and the list of low-confidence keys."""
        passport_fields, low = self._passport.extract(ctx)
        mrz = ctx.mrz
        dumped = passport_fields.model_dump()
        for drop in ("document_type", "mrz_line_3"):
            dumped.pop(drop, None)
        return (
            IdCardFields(
                **dumped,
                mrz_line_3=(mrz.raw_lines[2] if mrz and len(mrz.raw_lines) > 2 else None),
            ),
            low,
        )
