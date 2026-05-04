"""Application settings loaded from environment variables.

All configuration is centralized here. No hard-coded defaults are scattered
through the codebase — every tuning knob (preprocessing toggles, OCR thresholds,
rate-limit, CORS) is exposed as an env var.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration parsed from environment variables / .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # App
    app_name: str = Field(default="document-ocr-api")
    app_env: Literal["development", "production", "test"] = Field(default="development")
    log_level: str = Field(default="INFO")
    log_pii: bool = Field(default=False, description="If true, allow logging extracted PII fields.")

    # Server
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8000)
    workers: int = Field(default=2)

    # Upload limits
    max_file_size_mb: int = Field(default=10, ge=1, le=200)

    # OCR
    tesseract_cmd: str = Field(default="/usr/bin/tesseract")
    tesseract_langs: str = Field(default="uzb+uzb_cyrl+rus+eng")
    tesseract_psm: int = Field(default=6, ge=0, le=13)
    ocr_min_confidence: float = Field(default=60.0, ge=0, le=100)
    ocr_fallback_enabled: bool = Field(default=False)

    # PDF
    pdf_dpi: int = Field(default=300, ge=72, le=600)
    pdf_max_pages: int = Field(default=10, ge=1, le=100)

    # Preprocessing toggles. Threshold + denoise default OFF because most
    # uploaded documents are high-contrast photos/scans where Otsu+NLM hurt
    # OCR more than they help. Re-enable for noisy fax/photocopy inputs.
    preprocess_auto_orient: bool = Field(default=True)
    preprocess_deskew: bool = Field(default=True)
    preprocess_grayscale: bool = Field(default=True)
    preprocess_threshold: bool = Field(default=False)
    preprocess_denoise: bool = Field(default=False)
    preprocess_perspective_warp: bool = Field(default=True)

    # Security
    api_keys: str = Field(default="", description="Comma-separated list of valid API keys.")
    cors_origins: str = Field(default="*", description="Comma-separated allow-list or '*'.")
    rate_limit: str = Field(default="30/minute")

    # Observability
    enable_metrics: bool = Field(default=True)

    @property
    def max_file_size_bytes(self) -> int:
        """Return the configured max upload size in bytes."""
        return self.max_file_size_mb * 1024 * 1024

    @property
    def api_keys_set(self) -> set[str]:
        """Return the set of valid API keys (trimmed, empty values dropped)."""
        return {k.strip() for k in self.api_keys.split(",") if k.strip()}

    @property
    def cors_origins_list(self) -> list[str]:
        """Return parsed CORS origins as a list. '*' is preserved as a single entry."""
        raw = [o.strip() for o in self.cors_origins.split(",") if o.strip()]
        return raw or ["*"]

    @property
    def auth_enabled(self) -> bool:
        """API-key auth is enabled iff at least one key is configured."""
        return bool(self.api_keys_set)

    @field_validator("log_level")
    @classmethod
    def _upper_log_level(cls, v: str) -> str:
        return v.upper()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a process-wide cached Settings instance."""
    return Settings()
