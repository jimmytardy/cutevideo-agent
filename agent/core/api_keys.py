from __future__ import annotations

import base64
import json
import re
import uuid
from dataclasses import dataclass
from typing import Literal

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agent.core.config import settings
from agent.core.database import AsyncSessionFactory, UserApiKey

Provider = Literal[
    "anthropic", "gemini", "fal", "gcp", "azure_speech", "postforme", "zernio"
]
KeySource = Literal["user", "platform", "none"]
KeyTier = Literal["free", "paid"]

ALLOWED_PROVIDERS: frozenset[str] = frozenset(
    {"anthropic", "gemini", "fal", "gcp", "azure_speech", "postforme", "zernio"}
)

FREE_GEMINI_PURPOSES: frozenset[str] = frozenset(
    {
        "media_relevance_scoring",
        "video_analysis_critic",
        "diagram_layout",
        "llm_agent",
        "gemini_research",
        "gemini_tts",
        "search_anchor_translation",
    }
)


class ApiKeyNotConfiguredError(RuntimeError):
    pass


@dataclass
class ApiKeyContext:
    user_id: uuid.UUID | None
    provider: str
    key: str | None
    source: KeySource
    tier: KeyTier
    metadata: dict | None = None


@dataclass(frozen=True)
class GcpCredentials:
    project_id: str
    location: str
    credentials_json: str | None = None
    adc_path: str | None = None


def _configured_fernet(raw: str) -> Fernet:
    """Clé Fernet (base64 url-safe) ou 32 octets en hexadécimal (`openssl rand -hex 32`)."""
    if re.fullmatch(r"[0-9a-fA-F]{64}", raw):
        return Fernet(base64.urlsafe_b64encode(bytes.fromhex(raw)))
    return Fernet(raw.encode())


def _fernet() -> Fernet:
    """Unique clé de chiffrement des clés API : API_KEYS_ENCRYPTION_KEY (obligatoire)."""
    raw = settings.api_keys_encryption_key.strip()
    if not raw:
        raise RuntimeError("API_KEYS_ENCRYPTION_KEY manquante : impossible de chiffrer les clés API")
    return _configured_fernet(raw)


def encrypt_api_key(plain: str) -> str:
    return _fernet().encrypt(plain.encode()).decode()


def decrypt_api_key(encrypted: str) -> str:
    try:
        return _fernet().decrypt(encrypted.encode()).decode()
    except InvalidToken as exc:
        raise ValueError("Clé API chiffrée invalide") from exc


def format_api_key_hint(plain: str, visible_chars: int = 8) -> str:
    """Retourne le début de la clé pour affichage (sans exposer la valeur complète)."""
    cleaned = plain.strip()
    if not cleaned:
        return ""
    if len(cleaned) <= visible_chars:
        return cleaned
    return f"{cleaned[:visible_chars]}…"


def api_key_hint_from_encrypted(encrypted: str) -> str | None:
    try:
        return format_api_key_hint(decrypt_api_key(encrypted))
    except ValueError:
        return None


async def get_user_api_key_row(
    session: AsyncSession, user_id: uuid.UUID, provider: str
) -> UserApiKey | None:
    result = await session.execute(
        select(UserApiKey).where(
            UserApiKey.user_id == user_id,
            UserApiKey.provider == provider,
            UserApiKey.is_active.is_(True),
        )
    )
    return result.scalar_one_or_none()


def _platform_key(provider: str) -> tuple[str | None, dict | None]:
    if provider == "anthropic":
        return (settings.anthropic_api_key or None, None)
    if provider == "gemini":
        return (settings.google_gemini_api_key or None, None)
    if provider == "fal":
        return (settings.fal_key or None, None)
    if provider == "azure_speech":
        meta = {"region": settings.azure_speech_region}
        return (settings.azure_speech_key or None, meta)
    if provider == "gcp":
        if not settings.gcp_project_id:
            return (None, None)
        meta = {
            "project_id": settings.gcp_project_id,
            "location": settings.gcp_location,
            "credentials_path": settings.google_application_credentials,
        }
        return ("gcp-adc", meta)
    return (None, None)


async def resolve_api_key(
    session: AsyncSession,
    user_id: uuid.UUID | None,
    provider: str,
    *,
    purpose: str,
    tier: KeyTier = "free",
) -> ApiKeyContext:
    """Résout une clé API : BYOK user > plateforme (si autorisé) > none."""
    if provider not in ALLOWED_PROVIDERS:
        raise ValueError(f"Provider inconnu : {provider}")

    if user_id is not None:
        row = await get_user_api_key_row(session, user_id, provider)
        if row:
            return ApiKeyContext(
                user_id=user_id,
                provider=provider,
                key=decrypt_api_key(row.encrypted_key),
                source="user",
                tier=tier,
                metadata=row.metadata_,
            )

    platform_key, platform_meta = _platform_key(provider)
    allow_platform = False
    if provider == "gemini":
        allow_platform = purpose in FREE_GEMINI_PURPOSES or tier == "free"
    elif provider == "azure_speech" and purpose == "tts_azure":
        allow_platform = bool(platform_key)
    elif provider in ("fal", "gcp") and tier == "paid":
        allow_platform = bool(platform_key)

    if allow_platform and platform_key:
        return ApiKeyContext(
            user_id=user_id,
            provider=provider,
            key=platform_key,
            source="platform",
            tier="free" if provider == "gemini" and tier == "free" else tier,
            metadata=platform_meta,
        )

    return ApiKeyContext(
        user_id=user_id,
        provider=provider,
        key=None,
        source="none",
        tier=tier,
        metadata=None,
    )


async def fetch_api_key(
    user_id: uuid.UUID | None,
    provider: Provider,
    *,
    purpose: str,
    tier: KeyTier = "free",
) -> ApiKeyContext:
    """Résout une clé API avec une session DB éphémère."""
    async with AsyncSessionFactory() as session:
        return await resolve_api_key(
            session, user_id, provider, purpose=purpose, tier=tier
        )


def parse_gcp_credentials(ctx: ApiKeyContext) -> GcpCredentials | None:
    """Construit les credentials GCP à partir d'un ApiKeyContext résolu."""
    if ctx.source == "user" and ctx.key:
        meta = ctx.metadata or {}
        project_id = str(meta.get("project_id") or "").strip()
        location = str(meta.get("location") or settings.gcp_location).strip()
        if not project_id and ctx.key.strip().startswith("{"):
            try:
                data = json.loads(ctx.key)
                project_id = str(data.get("project_id") or "").strip()
            except json.JSONDecodeError:
                return None
        if not project_id:
            return None
        return GcpCredentials(
            project_id=project_id,
            location=location,
            credentials_json=ctx.key,
        )

    if ctx.source == "platform" and ctx.metadata:
        project_id = str(ctx.metadata.get("project_id") or "").strip()
        if not project_id:
            return None
        return GcpCredentials(
            project_id=project_id,
            location=str(ctx.metadata.get("location") or settings.gcp_location),
            adc_path=str(ctx.metadata.get("credentials_path") or "") or None,
        )
    return None
