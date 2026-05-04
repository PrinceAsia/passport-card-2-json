"""ID-card extractor tests (TD1 MRZ, OCR mocked)."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_id_card_extraction(
    client: TestClient,
    jpeg_bytes: bytes,
    id_card_text: str,
) -> None:
    client.app.state._stub_text = id_card_text
    files = {"file": ("id.jpg", jpeg_bytes, "image/jpeg")}
    r = client.post(
        "/api/v1/documents/extract", files=files, data={"document_type": "id_card"}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["document"]["detected_type"] == "id_card"
    fields = body["document"]["fields"]
    assert fields["mrz_line_3"] is not None
