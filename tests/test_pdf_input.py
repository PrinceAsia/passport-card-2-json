"""PDF input tests."""

from __future__ import annotations

import io

import fitz
from fastapi.testclient import TestClient


def _build_pdf(num_pages: int = 2) -> bytes:
    """Create a tiny in-memory PDF with `num_pages` blank pages."""
    doc = fitz.open()
    for _ in range(num_pages):
        doc.new_page(width=400, height=600)
    buf = io.BytesIO()
    doc.save(buf)
    doc.close()
    return buf.getvalue()


def test_pdf_multi_page(client: TestClient, passport_text: str) -> None:
    client.app.state._stub_text = passport_text
    files = {"file": ("doc.pdf", _build_pdf(2), "application/pdf")}
    r = client.post(
        "/api/v1/documents/extract", files=files, data={"document_type": "auto"}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["input"]["page_count"] == 2
    assert len(body["document"]["raw_text_per_page"]) == 2


def test_corrupt_pdf(client: TestClient) -> None:
    files = {"file": ("bad.pdf", b"not-a-pdf", "application/pdf")}
    r = client.post(
        "/api/v1/documents/extract", files=files, data={"document_type": "auto"}
    )
    assert r.status_code == 400
    assert r.json()["error_code"] == "INVALID_FILE"
