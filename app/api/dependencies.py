"""FastAPI dependency callables: API-key auth, rate-limit, request id."""

from __future__ import annotations

import uuid

from fastapi import Header, Request

from app.config import Settings, get_settings
from app.exceptions import UnauthorizedError


def get_request_id(request: Request) -> str:
    """Return a stable per-request UUID, generating one if not already attached."""
    rid = getattr(request.state, "request_id", None)
    if rid is None:
        rid = str(uuid.uuid4())
        request.state.request_id = rid
    return rid


async def require_api_key(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> None:
    """Validate the `X-API-Key` header against `Settings.api_keys_set`.

    No-op when no keys are configured (development mode).

    Raises:
        UnauthorizedError: when auth is enabled and the key is missing or invalid.
    """
    settings: Settings = get_settings()
    if not settings.auth_enabled:
        return
    if not x_api_key or x_api_key not in settings.api_keys_set:
        raise UnauthorizedError("Missing or invalid API key.")
