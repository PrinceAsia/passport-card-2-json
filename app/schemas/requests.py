"""Request-side schemas (form fields use FastAPI's Form, not JSON bodies)."""

from __future__ import annotations

from enum import StrEnum


class DocumentTypeRequest(StrEnum):
    """Allowed values for the optional `document_type` form field."""

    PASSPORT = "passport"
    ID_CARD = "id_card"
    BIRTH_CERTIFICATE = "birth_certificate"
    AUTO = "auto"
