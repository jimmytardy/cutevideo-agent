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
from agent.core.database import AsyncSessionFactory, User, UserApiKey

Provider = Literal[
    "anthropic", "gemini", "fal", "gcp", "azure_speech", "postforme", "zernio", "youtube", "instagram",
    "claude_subscription", "elevenlabs",
]
KeySource = Literal["user", "none"]
KeyTier = Literal["free", "paid"]

# Aucune clé de plateforme : chaque appel payant ou chaque publication utilise les
# identifiants du propriétaire (Compte → Clés API), sans repli sur le .env.
ALLOWED_PROVIDERS: frozenset[str] = frozenset(
    {"anthropic", "gemini", "fal", "gcp", "azure_speech", "postforme", "zernio", "youtube", "instagram",
     "claude_subscription", "elevenlabs"}
)
# Token d'abonnement Claude (`claude setup-token`) : réservé aux admins, pour leur propre usage.
# Anthropic interdit à une application de stocker les identifiants Claude.ai d'autres utilisateurs.
ADMIN_ONLY_PROVIDERS: frozenset[str] = frozenset({"claude_subscription"})


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


async def resolve_api_key(
    session: AsyncSession,
    user_id: uuid.UUID | None,
    provider: str,
    *,
    purpose: str,
    tier: KeyTier = "free",
) -> ApiKeyContext:
    """Clé de l'utilisateur pour ce fournisseur, sinon `source="none"` (jamais de clé plateforme).

    `purpose` sert au suivi des appels ; il ne change pas la résolution.
    """
    if provider not in ALLOWED_PROVIDERS:
        raise ValueError(f"Provider inconnu : {provider}")
    if provider in ADMIN_ONLY_PROVIDERS and user_id is not None:
        if not await session.scalar(select(User.is_admin).where(User.id == user_id)):
            user_id = None

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
    return ApiKeyContext(user_id=user_id, provider=provider, key=None, source="none", tier=tier)


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
    return None


@dataclass(frozen=True)
class UserKeys:
    """Clés payantes d'un utilisateur, résolues en une fois pour un run Claude Studio."""

    anthropic: str | None = None
    # Token d'abonnement Claude (admins seulement) : prioritaire sur la clé API pour le CLI.
    claude_subscription: str | None = None
    gemini: str | None = None
    fal: str | None = None
    azure_speech: str | None = None
    azure_speech_region: str | None = None
    gcp_credentials_json: str | None = None
    gcp_location: str | None = None
    elevenlabs: str | None = None


async def resolve_user_keys(user_id: uuid.UUID) -> UserKeys:
    async with AsyncSessionFactory() as session:
        ctx = {
            provider: await resolve_api_key(session, user_id, provider, purpose="studio")
            for provider in ("anthropic", "claude_subscription", "gemini", "fal", "azure_speech", "gcp", "elevenlabs")
        }
    azure_meta = ctx["azure_speech"].metadata or {}
    gcp_meta = ctx["gcp"].metadata or {}
    return UserKeys(
        anthropic=ctx["anthropic"].key,
        claude_subscription=ctx["claude_subscription"].key,
        gemini=ctx["gemini"].key,
        fal=ctx["fal"].key,
        azure_speech=ctx["azure_speech"].key,
        azure_speech_region=str(azure_meta.get("region") or "").strip() or None,
        gcp_credentials_json=ctx["gcp"].key,
        gcp_location=str(gcp_meta.get("location") or "").strip() or None,
        elevenlabs=ctx["elevenlabs"].key,
    )
