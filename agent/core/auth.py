from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from jose import JWTError, jwt

from agent.core.config import settings

ALGORITHM = "HS256"
TOKEN_TYPE_ACCESS = "access"
TOKEN_TYPE_OAUTH_STATE = "oauth_state"


def create_access_token(user_id: uuid.UUID, *, expires_minutes: int | None = None) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=expires_minutes or settings.jwt_expire_minutes
    )
    payload = {
        "sub": str(user_id),
        "type": TOKEN_TYPE_ACCESS,
        "exp": expire,
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=ALGORITHM)


def decode_access_token(token: str) -> uuid.UUID:
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[ALGORITHM])
        if payload.get("type") != TOKEN_TYPE_ACCESS:
            raise JWTError("Invalid token type")
        sub = payload.get("sub")
        if not sub:
            raise JWTError("Missing subject")
        return uuid.UUID(str(sub))
    except (JWTError, ValueError) as exc:
        raise ValueError("Token invalide ou expiré") from exc


def create_oauth_state(
    *,
    user_id: uuid.UUID | None = None,
    channel_id: uuid.UUID | None = None,
    purpose: str,
    extra: dict[str, Any] | None = None,
    expires_minutes: int = 15,
) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=expires_minutes)
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
