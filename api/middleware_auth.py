from __future__ import annotations

import uuid
from typing import Final

from fastapi import Request

USER_ID_STATE_KEY: Final = "auth_user_id"


PUBLIC_API_PREFIXES: Final = (
    "/api/v1/auth/google/login",
    "/api/v1/auth/google/callback",
    "/api/v1/channels/youtube/oauth/callback",
    "/health",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/storage/stats",
)


def is_public_api_path(path: str) -> bool:
    if path in PUBLIC_API_PREFIXES:
        return True
    if path.startswith("/api/v1/auth/google/"):
        return True
    if path.endswith("/connect/tiktok/callback"):
        return True
    return False


def resolve_request_auth_token(request: Request) -> str | None:
    """Extrait le JWT depuis Authorization Bearer ou ?access_token= (lecteurs média HTML)."""
    auth_header = request.headers.get("Authorization", "")
    if auth_header.lower().startswith("bearer "):
        token = auth_header[7:].strip()
        if token:
            return token
    query_token = request.query_params.get("access_token")
    if query_token:
        return query_token.strip()
    return None


def get_request_user_id(request: Request) -> uuid.UUID | None:
    raw = getattr(request.state, USER_ID_STATE_KEY, None)
    if raw is None:
        return None
    return uuid.UUID(str(raw))


def set_request_user_id(request: Request, user_id: uuid.UUID) -> None:
    setattr(request.state, USER_ID_STATE_KEY, str(user_id))
