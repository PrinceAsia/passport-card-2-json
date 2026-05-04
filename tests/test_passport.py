"""Happy-path test for passport extraction (OCR mocked)."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_passport_extraction(
    client: TestClient,
    jpeg_bytes: bytes,
    passport_text: str,
) -> None:
    client.app.state._stub_text = passport_text
    files = {"file": ("passport.jpg", jpeg_bytes, "image/jpeg")}
    r = client.post(
        "/api/v1/documents/extract", files=files, data={"document_type": "auto"}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["success"] is True
    assert body["document"]["detected_type"] == "passport"
    fields = body["document"]["fields"]
    assert fields["surname"] == "KARIMOV"
    assert fields["given_names"] == "ALISHER"
    assert fields["nationality"] == "UZB"
    assert fields["sex"] == "M"
    assert fields["date_of_birth"] == "1990-05-12"
    assert fields["mrz_line_1"] is not None
    assert fields["mrz_line_2"] is not None
