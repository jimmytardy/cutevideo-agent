"""Connexion par code Google Authenticator (TOTP)."""

from __future__ import annotations

import base64

import pytest
from fastapi import HTTPException

from agent.core import totp
from api.routes import auth

# Clé de test de la RFC 6238 (SHA-1) : "12345678901234567890".
RFC_SECRET = base64.b32encode(b"12345678901234567890").decode()


@pytest.mark.parametrize(
    ("t", "code"),
    [(59, "94287082"), (1111111109, "07081804"), (1234567890, "89005924"), (2000000000, "69279037")],
)
def test_rfc6238_vectors(t: int, code: str) -> None:
    assert totp.totp_now(RFC_SECRET, at=t, digits=8) == code


def test_verify_window_and_format() -> None:
    secret = totp.generate_secret()
    now = 1_700_000_000
    current = totp.totp_now(secret, at=now)
    assert totp.verify_totp(secret, current, at=now) == now // 30
    assert totp.verify_totp(secret, totp.totp_now(secret, at=now - 30), at=now) is not None
    assert totp.verify_totp(secret, totp.totp_now(secret, at=now - 90), at=now) is None
    assert totp.verify_totp(secret, "12345", at=now) is None
    assert totp.verify_totp(secret, "abcdef", at=now) is None
    assert totp.verify_totp("", current, at=now) is None


def test_provisioning_uri() -> None:
    uri = totp.provisioning_uri("ABC", "moi@ex.fr")
    assert uri.startswith("otpauth://totp/CuteVideo%3Amoi%40ex.fr?")
    assert "secret=ABC" in uri and "issuer=CuteVideo" in uri


class FakeRedis:
    def __init__(self) -> None:
        self.data: dict[str, int] = {}

    async def get(self, key: str):
        return self.data.get(key)

    async def set(self, key: str, value, ex: int | None = None) -> None:
        self.data[key] = int(value)

    async def incr(self, key: str) -> int:
        self.data[key] = self.data.get(key, 0) + 1
        return self.data[key]

    async def expire(self, key: str, seconds: int) -> None:
        pass

    async def delete(self, key: str) -> None:
        self.data.pop(key, None)


@pytest.fixture
def configured(monkeypatch: pytest.MonkeyPatch) -> str:
    secret = totp.generate_secret()
    monkeypatch.setattr(auth.settings, "totp_secret", secret)
    monkeypatch.setattr(auth.settings, "totp_login_email", "Moi@Ex.fr")
    return secret


@pytest.mark.asyncio
async def test_check_totp_accepts_once_then_refuses_replay(configured: str) -> None:
    redis = FakeRedis()
    code = totp.totp_now(configured)
    await auth.check_totp(redis, "moi@ex.FR", code, "1.2.3.4")  # e-mail sans tenir compte de la casse
    with pytest.raises(HTTPException) as exc:
        await auth.check_totp(redis, "moi@ex.fr", code, "1.2.3.4")
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_wrong_email_or_code_same_error_and_rate_limit(configured: str) -> None:
    redis = FakeRedis()
    good = totp.totp_now(configured)
    errors = []
    for email, code in [("autre@ex.fr", good), ("moi@ex.fr", "000000")]:
        with pytest.raises(HTTPException) as exc:
            await auth.check_totp(redis, email, code, "9.9.9.9")
        errors.append((exc.value.status_code, exc.value.detail))
    assert errors[0] == errors[1] == (401, auth.TOTP_INVALID)
    for _ in range(auth.TOTP_MAX_FAILURES - 2):
        with pytest.raises(HTTPException):
            await auth.check_totp(redis, "moi@ex.fr", "000000", "9.9.9.9")
    with pytest.raises(HTTPException) as exc:
        await auth.check_totp(redis, "moi@ex.fr", good, "9.9.9.9")  # même le bon code est bloqué
    assert exc.value.status_code == 429
    await auth.check_totp(redis, "moi@ex.fr", good, "5.5.5.5")  # autre IP : OK


def test_totp_disabled_without_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth.settings, "totp_secret", "")
    monkeypatch.setattr(auth.settings, "totp_login_email", "moi@ex.fr")
    assert auth.totp_enabled() is False


def test_totp_routes_are_public() -> None:
    from api.middleware_auth import is_public_api_path

    assert is_public_api_path("/api/v1/auth/totp/login")
    assert is_public_api_path("/api/v1/auth/totp/enabled")
