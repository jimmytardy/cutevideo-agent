from __future__ import annotations

import re
import uuid
from typing import Final

from fastapi import Request

from agent.core.auth import TokenKind

USER_ID_STATE_KEY: Final = "auth_user_id"

# Seules routes servies à des balises <video>/<audio>/<img> ou à un EventSource, qui ne peuvent pas envoyer
# d'en-tête Authorization : elles acceptent un jeton média court en `?access_token=` (agent/core/auth.py).
MEDIA_STREAM_PATH: Final = re.compile(
    r"^/api/v1/(?:"
    r"projects/[^/]+/(?:videos/[^/]+/stream|thumbnails/\d+/stream|studio/file)"
    r"|agents/runs/[^/]+/[^/]+/log/stream"
    r")$"
)


PUBLIC_API_PREFIXES: Final = (
    "/api/v1/auth/google/login",
    "/api/v1/auth/google/callback",
    "/api/v1/auth/totp/enabled",
    "/api/v1/auth/totp/login",
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


def is_media_stream_path(path: str) -> bool:
    return MEDIA_STREAM_PATH.match(path) is not None


def resolve_request_auth_token(request: Request) -> tuple[str, TokenKind] | None:
    """Jeton de la requête et son type attendu : `Authorization: Bearer` = jeton de session (`access`) ;
    `?access_token=` = jeton média court (`media`), uniquement sur les routes de flux."""
    auth_header = request.headers.get("Authorization", "")
    if auth_header.lower().startswith("bearer "):
        token = auth_header[7:].strip()
        if token:
            return token, "access"
    query_token = (request.query_params.get("access_token") or "").strip()
    if query_token and is_media_stream_path(request.url.path):
        return query_token, "media"
    return None


def get_request_user_id(request: Request) -> uuid.UUID | None:
    raw = getattr(request.state, USER_ID_STATE_KEY, None)
    if raw is None:
        return None
    return uuid.UUID(str(raw))


def set_request_user_id(request: Request, user_id: uuid.UUID) -> None:
    setattr(request.state, USER_ID_STATE_KEY, str(user_id))
