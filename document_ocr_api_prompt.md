# Prompt: Build a FastAPI Document OCR Service for Uzbek Identity Documents

## Role and Objective

You are a senior Python backend engineer. Your task is to build a production-ready **FastAPI** web service that accepts an uploaded identity document — specifically an **Uzbek passport, national ID card (ID-karta), or birth certificate (tug'ilganlik guvohnomasi)** — as either an **image** (JPG, JPEG, PNG, WEBP) or **PDF** file, performs OCR (Optical Character Recognition) on it, parses out every textual field, and returns the structured data as a clean JSON response.

The service must work for documents written in **Uzbek (Latin and Cyrillic)**, **Russian**, and **English** (MRZ/machine-readable zone), and must be robust to noisy scans, photos taken with a phone, rotated images, and multi-page PDFs.

---

## Functional Requirements

### 1. Endpoints

Implement the following REST endpoints:

- `POST /api/v1/documents/extract`
  - Accepts: `multipart/form-data` with a single file field named `file`.
  - Optional form field: `document_type` with allowed values: `passport`, `id_card`, `birth_certificate`, `auto` (default = `auto` — the service should auto-detect).
  - Optional form field: `language_hint` (e.g. `uz`, `ru`, `en`, or comma-separated like `uz,ru,en`). Default = `uz,ru,en`.
  - Returns: JSON object (see schema below).

- `GET /api/v1/health` — returns `{"status": "ok"}` for liveness checks.

- `GET /api/v1/supported-documents` — returns the list of supported document types and the fields each one provides.

- `GET /docs` — auto-generated Swagger UI (FastAPI default).

### 2. File Validation

- Accept only these MIME types: `image/jpeg`, `image/png`, `image/webp`, `application/pdf`.
- Maximum file size: **10 MB** (configurable via environment variable `MAX_FILE_SIZE_MB`).
- For PDFs: convert each page to an image (300 DPI) using `pdf2image` (poppler) or `PyMuPDF`. Process all pages and merge results.
- Reject corrupted files with HTTP `400` and a clear error message.

### 3. Image Pre-processing Pipeline

Before OCR, every image must pass through this pipeline (use **OpenCV** + **Pillow**):

1. Read into a NumPy array.
2. Auto-orient based on EXIF data.
3. Auto-rotate using Tesseract's `osd` (orientation and script detection) or a deskew algorithm.
4. Convert to grayscale.
5. Apply adaptive thresholding (or Otsu) for contrast enhancement.
6. Light denoising (`cv2.fastNlMeansDenoising`).
7. Optional: detect the document's quadrilateral and warp-perspective it to a flat rectangle (using contour detection) — only if the document occupies less than 80% of the image.

Make each pre-processing step toggleable through a config object so it can be tuned without code changes.

### 4. OCR Engine

- Primary engine: **Tesseract OCR** via `pytesseract`, with language packs `uzb`, `uzb_cyrl`, `rus`, `eng`.
- Fallback engine: **EasyOCR** (configurable). If Tesseract's average word confidence falls below a threshold (default `60`), automatically retry the same image with EasyOCR and merge the higher-confidence result.
- For the **MRZ zone** of passports/ID cards, use a dedicated parser: the [`PassportEye`](https://github.com/reubano/passporteye) library or a custom MRZ regex parser following ICAO Doc 9303. Always run MRZ extraction in parallel with the general OCR pass, because MRZ is far more reliable than visual fields.

### 5. Field Extraction & Parsing

Implement a **per-document-type extractor** module. Each extractor takes raw OCR text + bounding boxes and returns a typed Pydantic model.

#### a) Passport / ID-card fields

```
- document_type            (passport | id_card)
- document_number          (e.g. AA1234567)
- surname                  (Uzbek + transliterated)
- given_names
- nationality              (e.g. UZB)
- date_of_birth            (ISO 8601: YYYY-MM-DD)
- sex                      (M | F)
- place_of_birth
- date_of_issue            (ISO 8601)
- date_of_expiry           (ISO 8601)
- issuing_authority
- personal_number / PINFL  (14-digit Uzbek JShShIR)
- mrz_line_1
- mrz_line_2
- mrz_line_3               (only for ID cards, TD1 format)
- mrz_check_digits_valid   (boolean)
```

#### b) Birth certificate fields

```
- document_type            (birth_certificate)
- certificate_series       (e.g. "III-AB")
- certificate_number
- child_surname
- child_given_names
- child_date_of_birth      (ISO 8601)
- child_place_of_birth
- child_sex                (M | F)
- father_full_name
- father_nationality
- mother_full_name
- mother_nationality
- registry_office
- registration_number
- registration_date        (ISO 8601)
- date_of_issue            (ISO 8601)
```

All dates must be normalized to ISO 8601. Detect formats like `12.05.2010`, `12/05/2010`, `12 май 2010`, `2010-05-12` and convert them. If parsing fails, return the raw string in `*_raw` field.

### 6. Auto-detection of Document Type

If `document_type=auto`, classify the document using these signals (in order of priority):
1. Presence and pattern of MRZ → passport or ID card.
2. Keyword matches in the OCR text (Uzbek, Russian, English): "PASSPORT" / "ПАСПОРТ" / "PASPORT", "ID CARD" / "SHAXSIY GUVOHNOMA", "BIRTH CERTIFICATE" / "TUG'ILGANLIK HAQIDA GUVOHNOMA" / "СВИДЕТЕЛЬСТВО О РОЖДЕНИИ".
3. Layout cues (presence of photo region, machine-readable zone, registry-office stamps).

Return the detected type plus a `detection_confidence` score (0.0–1.0).

### 7. Response Schema

Return **JSON** with this exact top-level structure:

```json
{
  "success": true,
  "request_id": "uuid-v4",
  "processed_at": "2026-05-04T12:34:56Z",
  "processing_time_ms": 1837,
  "input": {
    "filename": "passport.jpg",
    "mime_type": "image/jpeg",
    "size_bytes": 482113,
    "page_count": 1
  },
  "document": {
    "detected_type": "passport",
    "detection_confidence": 0.97,
    "language_detected": ["uz", "en"],
    "fields": { ... typed fields per section 5 ... },
    "raw_text": "full OCR text concatenated from all pages",
    "raw_text_per_page": ["page 1 text", "page 2 text"]
  },
  "ocr_metadata": {
    "engine_primary": "tesseract",
    "engine_fallback_used": false,
    "avg_confidence": 87.4,
    "low_confidence_fields": ["place_of_birth"]
  },
  "warnings": [],
  "errors": []
}
```

On failure return `success: false` with HTTP `4xx`/`5xx` and a populated `errors` array — never crash with a stack trace exposed to the client.

### 8. Error Handling

Use FastAPI exception handlers to map exceptions to clean JSON responses:

| Condition                                | HTTP | Error code                |
|------------------------------------------|------|---------------------------|
| Wrong MIME type                          | 415  | UNSUPPORTED_MEDIA_TYPE    |
| File too large                           | 413  | FILE_TOO_LARGE            |
| Corrupted / unreadable file              | 400  | INVALID_FILE              |
| OCR returned empty text                  | 422  | OCR_EMPTY_RESULT          |
| No recognizable document found           | 422  | DOCUMENT_NOT_RECOGNIZED   |
| Internal error                           | 500  | INTERNAL_ERROR            |

Every error response must include `error_code`, `message`, `request_id`, and an optional `details` object.

### 9. Logging & Observability

- Use **structlog** or Python's `logging` with JSON formatter.
- Log every request with `request_id`, filename, MIME type, size, processing time, OCR confidence, detected type.
- Never log document field values (PII) unless an explicit `LOG_PII=true` env var is set (off by default).
- Add `/metrics` endpoint exposing Prometheus metrics: request count, request duration histogram, OCR confidence histogram, error counts by code.

### 10. Security & Privacy

- The service must not persist uploaded files to disk by default. Process everything in-memory using `tempfile.SpooledTemporaryFile`. If a temp file is needed for `pdf2image`, delete it immediately in a `finally` block.
- Sanitize file names; never use the user-supplied filename for any disk path.
- Add a configurable rate limiter (e.g. **slowapi**) — default 30 requests/minute per IP.
- Add CORS middleware, configurable via env var `CORS_ORIGINS`.
- Add a simple API-key middleware (header `X-API-Key`) that can be disabled in dev. The valid keys are read from the `API_KEYS` env var (comma-separated).

---

## Non-Functional Requirements

- Python **3.11+**.
- Type-hinted everywhere (`mypy --strict` should pass on the `app/` package).
- Async where it matters (file I/O, HTTP). OCR itself runs in a thread pool via `asyncio.to_thread` so it doesn't block the event loop.
- Response time goal: **< 3 seconds** for a single-page A4 image at 300 DPI on a 4-core CPU.
- All configuration via environment variables, parsed with **pydantic-settings**. Provide a `.env.example` file.

---

## Project Structure

Organize the codebase exactly like this:

```
document-ocr-api/
├── app/
│   ├── __init__.py
│   ├── main.py                     # FastAPI app factory, middleware, routers
│   ├── config.py                   # pydantic-settings Settings class
│   ├── api/
│   │   ├── __init__.py
│   │   ├── routes_documents.py
│   │   ├── routes_health.py
│   │   └── dependencies.py         # auth, rate-limit deps
│   ├── core/
│   │   ├── __init__.py
│   │   ├── preprocessing.py        # OpenCV pipeline
│   │   ├── ocr_engine.py           # Tesseract + EasyOCR wrappers
│   │   ├── mrz_parser.py
│   │   └── document_classifier.py  # auto-detect type
│   ├── extractors/
│   │   ├── __init__.py
│   │   ├── base.py                 # BaseExtractor abstract class
│   │   ├── passport.py
│   │   ├── id_card.py
│   │   └── birth_certificate.py
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── requests.py
│   │   └── responses.py            # all Pydantic response models
│   ├── utils/
│   │   ├── __init__.py
│   │   ├── date_parser.py
│   │   ├── pdf_utils.py
│   │   └── text_normalize.py
│   └── exceptions.py
├── tests/
│   ├── conftest.py
│   ├── test_passport.py
│   ├── test_id_card.py
│   ├── test_birth_certificate.py
│   ├── test_pdf_input.py
│   ├── test_validation.py
│   └── fixtures/                   # sample images (anonymized!)
├── docker/
│   ├── Dockerfile
│   └── docker-compose.yml
├── .env.example
├── pyproject.toml
├── README.md
└── Makefile
```

---

## Tech Stack (use exactly these)

- **fastapi**, **uvicorn[standard]**
- **pydantic v2**, **pydantic-settings**
- **python-multipart** (file uploads)
- **pillow**, **opencv-python-headless**, **numpy**
- **pytesseract** (system Tesseract with `uzb`, `uzb_cyrl`, `rus`, `eng`, `osd` packs)
- **easyocr** (optional fallback)
- **passporteye** for MRZ
- **pdf2image** (+ system `poppler-utils`) **or** **PyMuPDF** (`fitz`)
- **python-dateutil**
- **structlog**
- **slowapi** for rate limiting
- **prometheus-fastapi-instrumentator**
- **pytest**, **pytest-asyncio**, **httpx** for tests
- **ruff** + **black** + **mypy** for code quality

---

## Docker

Provide a multi-stage `Dockerfile` based on `python:3.11-slim` that installs `tesseract-ocr`, the Uzbek and Russian language packs, `poppler-utils`, and the Python deps. The final image must run as a non-root user. Provide a `docker-compose.yml` that spins up the API on port 8000.

---

## Tests

Write **pytest** tests covering:

- Happy path for each document type, using anonymized sample fixtures.
- Each error condition in the table above.
- PDF with multiple pages.
- Rotated and skewed images.
- Image with no document content (should return `DOCUMENT_NOT_RECOGNIZED`).
- MRZ check-digit validation logic (unit test, no I/O).
- Date parsing edge cases (`uz`, `ru`, `en` month names).

Aim for **≥ 80% coverage** on the `app/` package.

---

## Documentation

In `README.md` include:

1. Project description.
2. Quickstart (with and without Docker).
3. Required system dependencies (Tesseract, language packs, poppler).
4. Full env-var reference table.
5. Example `curl` request and response for each document type.
6. Notes on accuracy limitations and how to tune the preprocessing pipeline.
7. A privacy/PII section describing the no-persistence default.

---

## Deliverables

1. The full source tree as described.
2. A working `docker compose up` that exposes the service on `localhost:8000`.
3. All tests passing locally.
4. `README.md` and `.env.example`.

---

## Coding Style Rules

- No bare `except:`. Catch specific exceptions only.
- No print statements — use the logger.
- No hard-coded secrets, paths, or magic numbers — pull from `Settings`.
- Every public function has a docstring including a brief description, args, returns, and raises.
- Pydantic models use `Field(..., description=...)` so the OpenAPI docs are useful.
- Keep functions under 50 lines where reasonable; extract helpers.

---

## Final Instructions

Build the project end-to-end. Start by listing the file tree you will create, then generate every file in full — no placeholders, no `# TODO`, no "rest of the implementation goes here". After producing the code, run a self-review pass and explicitly state:

- Whether `mypy --strict app/` would pass.
- Whether each endpoint matches the schemas defined above.
- Any assumptions you made that the user should validate (especially around Uzbek-specific document layouts and field labels).
