"""Per-document-type field extractors."""

from app.extractors.base import BaseExtractor, ExtractionContext
from app.extractors.birth_certificate import BirthCertificateExtractor
from app.extractors.id_card import IdCardExtractor
from app.extractors.passport import PassportExtractor

__all__ = [
    "BaseExtractor",
    "BirthCertificateExtractor",
    "ExtractionContext",
    "IdCardExtractor",
    "PassportExtractor",
]
