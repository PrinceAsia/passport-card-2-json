"""Birth-certificate extractor tests (no MRZ)."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_birth_cert_extraction(
    client: TestClient,
    jpeg_bytes: bytes,
    birth_cert_text: str,
) -> None:
    client.app.state._stub_text = birth_cert_text
    files = {"file": ("birth.jpg", jpeg_bytes, "image/jpeg")}
    r = client.post(
        "/api/v1/documents/extract",
        files=files,
        data={"document_type": "auto"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["document"]["detected_type"] == "birth_certificate"
    fields = body["document"]["fields"]
    assert fields["certificate_series"] == "III-AB"
    assert fields["child_date_of_birth"] == "2010-05-12"


def test_unknown_document(client: TestClient, jpeg_bytes: bytes) -> None:
    client.app.state._stub_text = "Lorem ipsum dolor sit amet."
    files = {"file": ("noise.jpg", jpeg_bytes, "image/jpeg")}
    r = client.post(
        "/api/v1/documents/extract", files=files, data={"document_type": "auto"}
    )
    assert r.status_code == 422
    assert r.json()["error_code"] == "DOCUMENT_NOT_RECOGNIZED"


def test_empty_ocr_result(client: TestClient, jpeg_bytes: bytes) -> None:
    client.app.state._stub_text = ""
    files = {"file": ("blank.jpg", jpeg_bytes, "image/jpeg")}
    r = client.post(
        "/api/v1/documents/extract", files=files, data={"document_type": "auto"}
    )
    assert r.status_code == 422
    assert r.json()["error_code"] == "OCR_EMPTY_RESULT"
