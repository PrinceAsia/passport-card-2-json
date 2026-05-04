# syntax=docker/dockerfile:1.7
# ----- Stage 1: build wheels --------------------------------------------------
FROM python:3.11-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /build

# Build essentials needed by some Python wheels (numpy fallback, opencv).
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        gcc \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY app ./app

RUN pip install --upgrade pip && \
    pip wheel --wheel-dir=/wheels .

# ----- Stage 2: runtime -------------------------------------------------------
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TESSDATA_PREFIX=/usr/share/tesseract-ocr/5/tessdata/

# Tesseract + Uzbek/Russian/English language packs + OSD; no poppler needed
# because we render PDFs with PyMuPDF.
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-eng \
        tesseract-ocr-rus \
        tesseract-ocr-uzb \
        tesseract-ocr-uzb-cyrl \
        tesseract-ocr-osd \
        libgl1 \
        libglib2.0-0 \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Non-root runtime user.
RUN groupadd --system app && useradd --system --gid app --home /app app

WORKDIR /app

COPY --from=builder /wheels /wheels
COPY pyproject.toml ./
COPY app ./app

RUN pip install --upgrade pip && \
    pip install --no-index --find-links=/wheels document-ocr-api && \
    rm -rf /wheels

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/api/v1/health || exit 1

CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
