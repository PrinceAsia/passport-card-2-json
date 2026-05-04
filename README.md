# Document OCR API

Production-ready FastAPI service that extracts structured data from **Uzbek
passports, national ID cards (shaxsiy guvohnoma) and birth certificates
(tug'ilganlik haqida guvohnoma)**. Accepts JPG/PNG/WEBP/PDF and returns clean
JSON with normalized dates, MRZ data, and per-field confidence flags.

## Features

- Auto-detection of document type from MRZ format + multilingual keywords
  (uz Latin, uz Cyrillic, ru, en).
- **Two-pass MRZ extraction**: PassportEye on the original image *plus* a
  dedicated bottom-strip Tesseract pass with a Latin-only character whitelist —
  recovers MRZs even when full-page OCR mis-reads them as Cyrillic on
  dual-script Uzbek passports.
- ICAO 9303 MRZ parser (TD1 + TD3) with check-digit validation; Cyrillic→Latin
  homoglyph normalization (`А→A, В→B, Е→E, …`).
- Label-positional field extractor: finds Cyrillic / Latin / Russian / English
  labels and captures the next-line or trailing-inline value, with apostrophe
  normalization so OCR variants (`Tug'ilgan'sanasi`) still match.
- OpenCV preprocessing pipeline: EXIF orient, deskew, grayscale, threshold,
  denoise, perspective warp — every step independently toggleable via env vars.
- Tesseract primary + optional EasyOCR fallback when confidence is low.
- Multi-page PDF support via PyMuPDF (no poppler required).
- Structured JSON logs (structlog), Prometheus metrics, request IDs.
- API-key auth, per-IP rate limiting, CORS — all env-configurable.
- No persistence: documents are processed in-memory.

## Quickstart — Docker

```bash
cp .env.example .env
docker compose -f docker/docker-compose.yml up --build
```

Service is now on `http://localhost:8000`. Open `http://localhost:8000/docs` for
the Swagger UI.

## Quickstart — local

System packages required:

```bash
sudo apt-get install -y \
    tesseract-ocr tesseract-ocr-eng tesseract-ocr-rus \
    tesseract-ocr-uzb tesseract-ocr-uzb-cyrl tesseract-ocr-osd \
    libgl1 libglib2.0-0
```

Python 3.11+:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"        # add ",fallback" for EasyOCR
cp .env.example .env
make dev                       # uvicorn on :8000
```

Run tests:

```bash
make test          # unit + real-fixture integration tests
```

The integration suite (`tests/test_real_fixtures.py`) runs the full pipeline
against the bundled sample images. It is **automatically skipped** when the
system `tesseract` binary is not on `PATH`, so the unit suite alone runs fine
on CI without OCR dependencies.

## API

### `POST /api/v1/documents/extract`

`multipart/form-data` with:

| field           | required | description                                               |
|-----------------|----------|-----------------------------------------------------------|
| `file`          | yes      | image (`image/jpeg`,`png`,`webp`) or `application/pdf`     |
| `document_type` | no       | `passport`, `id_card`, `birth_certificate`, or `auto`      |
| `language_hint` | no       | comma-separated codes — `uz,ru,en` (default)              |

Example:

```bash
curl -X POST http://localhost:8000/api/v1/documents/extract \
     -H "X-API-Key: dev-key" \
     -F "file=@passport.jpg" \
     -F "document_type=auto"
```

Sample response (truncated):

```json
{
  "success": true,
  "request_id": "8b3e0d20-...",
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
    "fields": {
      "document_type": "passport",
      "document_number": "AA1234567",
      "surname": "KARIMOV",
      "given_names": "ALISHER",
      "nationality": "UZB",
      "date_of_birth": "1990-05-12",
      "sex": "M",
      "date_of_expiry": "2030-01-01",
      "mrz_check_digits_valid": true
    },
    "raw_text": "...",
    "raw_text_per_page": ["..."]
  },
  "ocr_metadata": {
    "engine_primary": "tesseract",
    "engine_fallback_used": false,
    "avg_confidence": 87.4,
    "low_confidence_fields": []
  },
  "warnings": [],
  "errors": []
}
```

### Other endpoints

- `GET /api/v1/health` — liveness probe
- `GET /api/v1/supported-documents` — manifest of supported types and fields
- `GET /metrics` — Prometheus metrics (when `ENABLE_METRICS=true`)
- `GET /docs` — Swagger UI

## Error envelope

```json
{
  "success": false,
  "request_id": "uuid-v4",
  "error_code": "FILE_TOO_LARGE",
  "message": "File exceeds the 10 MB limit.",
  "details": {"size_bytes": 12582912, "limit_bytes": 10485760}
}
```

| Condition                     | HTTP | `error_code`              |
|-------------------------------|------|---------------------------|
| Wrong MIME type               | 415  | `UNSUPPORTED_MEDIA_TYPE`  |
| File too large                | 413  | `FILE_TOO_LARGE`          |
| Corrupted / unreadable file   | 400  | `INVALID_FILE`            |
| OCR returned empty text       | 422  | `OCR_EMPTY_RESULT`        |
| No recognizable document      | 422  | `DOCUMENT_NOT_RECOGNIZED` |
| Missing/invalid API key       | 401  | `UNAUTHORIZED`            |
| Rate limit exceeded           | 429  | `RATE_LIMITED`            |
| Internal error                | 500  | `INTERNAL_ERROR`          |

## Configuration

| Variable                       | Default                       | Description |
|--------------------------------|-------------------------------|-------------|
| `APP_ENV`                      | `development`                 | `development`/`production`/`test` |
| `LOG_LEVEL`                    | `INFO`                        | stdlib level |
| `LOG_PII`                      | `false`                       | If true, allow logging extracted field values |
| `HOST` / `PORT` / `WORKERS`    | `0.0.0.0:8000`, 2             | uvicorn binding |
| `MAX_FILE_SIZE_MB`             | `10`                          | Upload limit |
| `TESSERACT_CMD`                | `/usr/bin/tesseract`          | Path to tesseract binary |
| `TESSERACT_LANGS`              | `uzb+uzb_cyrl+rus+eng`        | `--lang` arg passed to tesseract |
| `TESSERACT_PSM`                | `6`                           | Page segmentation mode |
| `OCR_MIN_CONFIDENCE`           | `60`                          | Below this, fallback engine kicks in |
| `OCR_FALLBACK_ENABLED`         | `false`                       | Set true after `pip install ".[fallback]"` |
| `PDF_DPI`                      | `300`                         | PyMuPDF render DPI |
| `PDF_MAX_PAGES`                | `10`                          | Hard cap on PDF pages |
| `PREPROCESS_AUTO_ORIENT`       | `true`                        | Honor EXIF orientation |
| `PREPROCESS_DESKEW`            | `true`                        | Estimate + correct rotation |
| `PREPROCESS_GRAYSCALE`         | `true`                        | Convert to single channel |
| `PREPROCESS_PERSPECTIVE_WARP`  | `true`                        | Detect document quad and rectify |
| `PREPROCESS_THRESHOLD`         | **`false`**                   | Otsu threshold — enable for low-contrast scans |
| `PREPROCESS_DENOISE`           | **`false`**                   | Non-local-means denoise — enable for grainy scans |
| `API_KEYS`                     | *(empty)*                     | Comma-separated valid keys; empty disables auth |
| `CORS_ORIGINS`                 | `*`                           | Comma-separated origins |
| `RATE_LIMIT`                   | `30/minute`                   | slowapi format |
| `ENABLE_METRICS`               | `true`                        | Expose `/metrics` |

## Tuning the preprocessing pipeline

The default profile (`PREPROCESS_THRESHOLD=false`, `PREPROCESS_DENOISE=false`)
is tuned for **clean phone photos and modern scans**, which is the most common
real-world input. Otsu thresholding and NLM denoising tend to hurt those by
flattening anti-aliased glyphs.

For **noisy fax/photocopy/old-passport scans** with low contrast, flip both
on:

```bash
PREPROCESS_THRESHOLD=true
PREPROCESS_DENOISE=true
```

If Tesseract confidence is consistently below `OCR_MIN_CONFIDENCE` (default
60), enabling EasyOCR raises recall on Latin/Cyrillic visual fields:

```bash
pip install -e ".[fallback]"
OCR_FALLBACK_ENABLED=true
```

## Privacy & PII

By design, the service:

- **Never persists** uploaded files. PDFs are rendered in memory; images are
  read straight from `UploadFile` into a `bytes` buffer.
- **Never logs** extracted field values unless `LOG_PII=true`. Only metadata
  (request ID, file size, MIME type, processing time, average confidence) is
  written to the structured log.
- **Sanitizes filenames** before echoing them in the response.

For production deployments behind a reverse proxy, set `CORS_ORIGINS` to the
specific allow-list and configure `API_KEYS` rather than leaving auth disabled.

## Accuracy notes

- MRZ extraction is far more reliable than visual fields. When an MRZ is
  recovered, it overrides the corresponding visual reads (surname, document
  number, DOB, expiry, sex, nationality). Two parsing paths run in parallel:
  PassportEye on the original image, and a dedicated bottom-strip Tesseract
  pass with a Latin-only character whitelist + Cyrillic→Latin homoglyph
  mapping. The strongest candidate (validated check digits → most populated)
  wins.
- Birth certificates have no MRZ and use template-driven label heuristics.
  Older or photographed templates (`birth_cert_3.jpg`-style) often yield only
  the registry office and certificate number; the `low_confidence_fields` list
  reports gaps and the `*_raw` siblings preserve unparseable strings.
- Phone photos: ensure the document fills ≥30% of the frame and is not
  back-lit. The perspective-warp step handles small skews/rotations
  automatically.
- **Date-pair labels**: when issue & expiry labels collapse onto one OCR line
  ("БЕРИЛГАН ВАКТИ ... АМАЛ ҚИЛИШ МУХЛАТИ"), the extractor recovers the second
  date on the value line as the expiry. Verified against the bundled
  `Uzbekistan_Pasport_(old).jpg` fixture.
- **Cross-contaminated labels** ("МИЛЛАТИ ТУҒИЛГАН ЖОЙИ" merged): when the
  nationality and place-of-birth captures collapse to the same merged value,
  the first token becomes nationality and the rest becomes place of birth.

## Development

```bash
make lint     # ruff
make format   # black + ruff --fix
make type     # mypy --strict app
make test     # pytest with coverage
```

## License

MIT.
