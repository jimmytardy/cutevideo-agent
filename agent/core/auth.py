from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta, UTC
from typing import Any, Literal

from jose import JWTError, jwt

from agent.core.config import settings

ALGORITHM = "HS256"
TOKEN_TYPE_ACCESS = "access"
TOKEN_TYPE_OAUTH_STATE = "oauth_state"
# Jeton court pour les URL média (balises <video>/<img>, EventSource : pas d'en-tête Authorization possible) :
# passé en `?access_token=`, accepté uniquement sur les routes de flux (api/middleware_auth.py), jamais en header.
TOKEN_TYPE_MEDIA = "media"
MEDIA_TOKEN_MINUTES = 15

# Provenance d'un jeton dans une requête : en-tête Authorization (`access`) ou query des routes de flux (`media`).
TokenKind = Literal["access", "media"]
_TOKEN_TYPES: dict[str, str] = {"access": TOKEN_TYPE_ACCESS, "media": TOKEN_TYPE_MEDIA}


def _create_subject_token(user_id: uuid.UUID, token_type: str, minutes: int) -> str:
    payload = {"sub": str(user_id), "type": token_type, "exp": datetime.now(UTC) + timedelta(minutes=minutes)}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=ALGORITHM)


def _decode_subject(token: str, expected_type: str) -> uuid.UUID:
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[ALGORITHM])
        if payload.get("type") != expected_type:
            raise JWTError("Invalid token type")
        sub = payload.get("sub")
        if not sub:
            raise JWTError("Missing subject")
        return uuid.UUID(str(sub))
    except (JWTError, ValueError) as exc:
        raise ValueError("Token invalide ou expiré") from exc


def create_access_token(user_id: uuid.UUID, *, expires_minutes: int | None = None) -> str:
    return _create_subject_token(user_id, TOKEN_TYPE_ACCESS, expires_minutes or settings.jwt_expire_minutes)


def decode_token(token: str, kind: TokenKind) -> uuid.UUID:
    """Décode un jeton selon sa provenance ; un jeton d'un autre type est refusé (ValueError)."""
    return _decode_subject(token, _TOKEN_TYPES[kind])


def decode_access_token(token: str) -> uuid.UUID:
    return decode_token(token, "access")


def create_media_token(user_id: uuid.UUID) -> str:
    return _create_subject_token(user_id, TOKEN_TYPE_MEDIA, MEDIA_TOKEN_MINUTES)


def decode_media_token(token: str) -> uuid.UUID:
    return decode_token(token, "media")


def create_oauth_state(
    *,
    user_id: uuid.UUID | None = None,
    channel_id: uuid.UUID | None = None,
    purpose: str,
    extra: dict[str, Any] | None = None,
    expires_minutes: int = 15,
) -> str:
    expire = datetime.now(UTC) + timedelta(minutes=expires_minutes)
    payload: dict[str, Any] = {
        "type": TOKEN_TYPE_OAUTH_STATE,
        "purpose": purpose,
        "nonce": secrets.token_urlsafe(16),
        "exp": expire,
    }
    if user_id:
        payload["user_id"] = str(user_id)
    if channel_id:
        payload["channel_id"] = str(channel_id)
    if extra:
        payload["extra"] = extra
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=ALGORITHM)


def decode_oauth_state(token: str, *, expected_purpose: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[ALGORITHM])
        if payload.get("type") != TOKEN_TYPE_OAUTH_STATE:
            raise JWTError("Invalid state type")
        if payload.get("purpose") != expected_purpose:
            raise JWTError("Invalid state purpose")
        return payload
    except JWTError as exc:
        raise ValueError("State OAuth invalide ou expiré") from exc
