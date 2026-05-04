# Project conventions

FastAPI OCR service for **Uzbek passports, ID cards, and birth certificates**.
Tesseract primary, optional EasyOCR fallback, PyMuPDF for PDFs. No persistence.

## Local environment

- Python venv: `.venv/` (Python 3.12). Use `.venv/bin/python`, `.venv/bin/pytest`,
  `.venv/bin/mypy`, `.venv/bin/ruff` directly — no `source activate` needed.
- System Tesseract is at `/usr/bin/tesseract` with `eng + rus + uzb + uzb_cyrl + osd`
  language packs. Verify with `tesseract --list-langs`.
- Sample documents live in `test-docs/` (project root, originals) and
  `tests/fixtures/` (copies wired into the integration suite).

## Commands

```bash
make test          # pytest — runs unit + real-fixture integration suites
make type          # mypy --strict app  (must pass; 27 source files)
make lint          # ruff check
make format        # black + ruff --fix
make dev           # uvicorn --reload on :8000
```

`pytest` automatically skips `tests/test_real_fixtures.py` when `tesseract`
is missing, so unit tests run on bare CI.

## Architecture map

```
app/
├── api/routes_documents.py     # POST /api/v1/documents/extract — entry
├── services/extraction.py      # Sync orchestrator — runs in asyncio.to_thread
├── core/
│   ├── preprocessing.py        # OpenCV pipeline (toggleable per env var)
│   ├── ocr_engine.py           # Tesseract + lazy EasyOCR + run_mrz_zone()
│   ├── mrz_parser.py           # ICAO 9303 TD1/TD3 + check digits + homoglyphs
│   └── document_classifier.py  # MRZ format + multilingual keywords
├── extractors/                 # base + passport + id_card + birth_certificate
└── schemas/                    # pydantic v2 request/response models
```

## Behaviors that surprise

- **Preprocessing defaults**: `PREPROCESS_THRESHOLD` and `PREPROCESS_DENOISE`
  default to **`false`** in `Settings`. Otsu + NLM hurt clean phone photos
  more than they help. Re-enable for noisy scans only.
- **MRZ runs twice per page**: PassportEye on the original page + a dedicated
  bottom-30% Tesseract crop with Latin-only whitelist (`run_mrz_zone`). The
  second pass exists because dual-script Uzbek passports cause Tesseract to
  read the MRZ as Cyrillic — `mrz_parser._MRZ_CHAR_MAP` then maps Cyrillic
  homoglyphs (А→A, В→B, …) before regex matching. **Don't add `O→0` or `Q→0`
  to that map** — the surname positions contain real letters.
- **Field extractor preference order**: in `BaseExtractor.find_value_after_label`,
  next-line wins over inline for non-pattern (text) fields, but inline wins
  for pattern (date / number) fields. This is deliberate — a 1-char OCR glyph
  attached to a label ("Authority u") would otherwise hijack the capture.
- **TD3 line ordering**: `parse_mrz_from_text` does *not* assume positional
  order. It identifies line 1 by the leading `P<` character and line 2 by
  exclusion, because OCR sometimes emits them swapped.
- **Issue/expiry on one line**: when both date labels share a line, the same
  date matches for both. `PassportExtractor._second_date_after_label` recovers
  the second `_DATE_RE` match on the value line for expiry.
- **Nationality + place_of_birth collapse**: when both labels are emitted on
  one OCR line, both fields capture the same merged value
  (`"ЎЗБЕК ТОШКЕНТ"`). `_split_nationality_and_place` un-collapses by
  splitting on whitespace.
- `IdCardExtractor` uses **composition** with `PassportExtractor`, not
  inheritance, to keep the typed return signature `tuple[IdCardFields, ...]`
  Liskov-clean under `mypy --strict`.

## When fields don't extract

Run the live debugger first:

```bash
.venv/bin/python -c "
import os
os.environ['ENABLE_METRICS']='false'; os.environ['API_KEYS']=''
from app.config import get_settings; get_settings.cache_clear()
from app.services.extraction import process_upload
from app.schemas.requests import DocumentTypeRequest
data = open('test-docs/<filename>', 'rb').read()
r = process_upload(data=data, filename='x.jpg', mime_type='image/jpeg',
    document_type=DocumentTypeRequest.AUTO, language_hint='uz,ru,en', request_id='dbg')
print(r.document.raw_text)              # see what OCR actually produced
print(r.document.fields.model_dump())
"
```

Diagnostic order:
1. **Look at `raw_text` first.** If the value isn't visible there, no extractor
   change will help — it's a Tesseract / preprocessing issue. Try toggling
   `PREPROCESS_THRESHOLD` and `PREPROCESS_DENOISE` and re-run.
2. If the value *is* in `raw_text` but not in the extracted fields, the label
   dictionary in the relevant `extractors/*.py` is missing a variant. Add it.
3. If MRZ is present in `raw_text` but not extracted, check
   `mrz_parser._MRZ_CHAR_MAP` — a new Cyrillic homoglyph may need adding, or
   `_TD3_LINE_RE` / `_TD1_LINE_RE` may need a slightly wider length window.

## Known limits

- `birth_cert_3.jpg` and `birth_cert_2_BAD.jpg` extract little — OCR limit, not
  a code bug. The integration suite covers the 4 readable fixtures.
- `ID_Card_2.jpg` DOB is missing because the date sits visually next to the
  photo region and Tesseract cannot recover it without per-template region
  cropping. Out of scope without an ML layout model.
