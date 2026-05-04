"""Endpoint validation tests: MIME, size, empty file, etc."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_health(client: TestClient) -> None:
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_supported_documents(client: TestClient) -> None:
    r = client.get("/api/v1/supported-documents")
    assert r.status_code == 200
    body = r.json()
    types = [d["document_type"] for d in body["documents"]]
    assert types == ["passport", "id_card", "birth_certificate"]


def test_extract_rejects_unsupported_mime(client: TestClient) -> None:
    files = {"file": ("hello.txt", b"hi", "text/plain")}
    r = client.post("/api/v1/documents/extract", files=files)
    assert r.status_code == 415
    assert r.json()["error_code"] == "UNSUPPORTED_MEDIA_TYPE"


def test_extract_rejects_empty_file(client: TestClient) -> None:
    files = {"file": ("empty.png", b"", "image/png")}
    r = client.post("/api/v1/documents/extract", files=files)
    assert r.status_code == 400
    assert r.json()["error_code"] == "INVALID_FILE"


def test_extract_rejects_oversize(
    client: TestClient,
    monkeypatch: object,  # noqa: ARG001
    jpeg_bytes: bytes,
) -> None:
    big = jpeg_bytes + b"\x00" * (11 * 1024 * 1024)
    files = {"file": ("big.jpg", big, "image/jpeg")}
    r = client.post("/api/v1/documents/extract", files=files)
    assert r.status_code == 413
    assert r.json()["error_code"] == "FILE_TOO_LARGE"


def test_extract_invalid_image_bytes(client: TestClient) -> None:
    files = {"file": ("not-an-image.jpg", b"NOT-A-JPEG", "image/jpeg")}
    r = client.post("/api/v1/documents/extract", files=files)
    assert r.status_code == 400
    assert r.json()["error_code"] == "INVALID_FILE"
