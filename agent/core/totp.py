"""Codes TOTP (RFC 6238, compatibles Google Authenticator) sans dépendance externe."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote, urlencode

STEP_S = 30
DIGITS = 6


def _key(secret: str) -> bytes:
    cleaned = secret.replace(" ", "").upper()
    return base64.b32decode(cleaned + "=" * (-len(cleaned) % 8))


def hotp(key: bytes, counter: int, digits: int = DIGITS) -> str:
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset: offset + 4])[0] & 0x7FFFFFFF
    return str(value % 10**digits).zfill(digits)


def totp_now(secret: str, at: float | None = None, digits: int = DIGITS) -> str:
    return hotp(_key(secret), int((time.time() if at is None else at) // STEP_S), digits)


def verify_totp(secret: str, code: str, *, at: float | None = None, window: int = 1) -> int | None:
    """Renvoie le pas de temps accepté (pour l'anti-rejeu), ou None si le code est faux."""
    code = (code or "").strip().replace(" ", "")
    if not secret or len(code) != DIGITS or not code.isdigit():
        return None
    key = _key(secret)
    step = int((time.time() if at is None else at) // STEP_S)
    for candidate in range(step - window, step + window + 1):
        if hmac.compare_digest(hotp(key, candidate), code):
            return candidate
    return None


def generate_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def provisioning_uri(secret: str, email: str, issuer: str = "CuteVideo") -> str:
    label = quote(f"{issuer}:{email}")
    return f"otpauth://totp/{label}?" + urlencode(
        {"secret": secret, "issuer": issuer, "algorithm": "SHA1", "digits": DIGITS, "period": STEP_S}
    )
