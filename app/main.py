"""FastAPI application factory.

Wires together middleware (CORS, request id, rate limit), routers, exception
handlers, structured logging, and Prometheus instrumentation.
"""

from __future__ import annotations

import logging
import sys
import uuid
from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.routes_documents import router as documents_router
from app.api.routes_health import router as health_router
from app.config import Settings, get_settings
from app.exceptions import ErrorCode, OCRApiError
from app.schemas.responses import ErrorResponse


def _configure_logging(settings: Settings) -> None:
    """Wire `structlog` on top of the stdlib logger with a JSON output formatter."""
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=settings.log_level,
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, settings.log_level, logging.INFO)
        ),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Attach a request ID to `request.state` and the `X-Request-ID` response header."""

    async def dispatch(self, request: Request, call_next: Any) -> Any:
        request.state.request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response


def _install_exception_handlers(app: FastAPI) -> None:
    """Register exception handlers that produce `ErrorResponse` JSON envelopes."""
    log = structlog.get_logger("errors")

    @app.exception_handler(OCRApiError)
    async def domain_handler(request: Request, exc: OCRApiError) -> JSONResponse:
        rid = getattr(request.state, "request_id", "unknown")
        log.warning(
            "request.domain_error",
            request_id=rid,
            error_code=exc.error_code,
            message=exc.message,
        )
        body = ErrorResponse(
            request_id=rid,
            error_code=exc.error_code,
            message=exc.message,
            details=exc.details or None,
        )
        return JSONResponse(status_code=exc.status_code, content=body.model_dump(mode="json"))

    @app.exception_handler(RateLimitExceeded)
    async def rate_limit_handler(request: Request, exc: Exception) -> JSONResponse:
        rid = getattr(request.state, "request_id", "unknown")
        detail = getattr(exc, "detail", "rate limit exceeded")
        body = ErrorResponse(
            request_id=rid,
            error_code=ErrorCode.RATE_LIMITED,
            message="Rate limit exceeded.",
            details={"limit": str(detail)},
        )
        return JSONResponse(status_code=429, content=body.model_dump(mode="json"))

    @app.exception_handler(Exception)
    async def fallback_handler(request: Request, exc: Exception) -> JSONResponse:
        rid = getattr(request.state, "request_id", "unknown")
        log.exception("request.unhandled", request_id=rid)
        body = ErrorResponse(
            request_id=rid,
            error_code=ErrorCode.INTERNAL_ERROR,
            message="An internal error occurred.",
        )
        return JSONResponse(status_code=500, content=body.model_dump(mode="json"))


def create_app() -> FastAPI:
    """Application factory used by uvicorn (`--factory`) and tests."""
    settings = get_settings()
    _configure_logging(settings)

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description=(
            "OCR service for Uzbek passports, ID cards, and birth certificates. "
            "Returns structured JSON extracted from images or PDFs."
        ),
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    limiter = Limiter(key_func=get_remote_address, default_limits=[settings.rate_limit])
    app.state.limiter = limiter
    app.add_middleware(SlowAPIMiddleware)

    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health_router, prefix="/api/v1", tags=["health"])
    app.include_router(documents_router, prefix="/api/v1", tags=["documents"])

    _install_exception_handlers(app)

    if settings.enable_metrics:
        Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)

    return app


app = create_app()
