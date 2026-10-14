"""Identifiants de publication d'une chaîne.

Tout vient du propriétaire de la chaîne, sans repli global ni admin :
- YouTube : le token OAuth de la chaîne, sinon le refresh token du compte Google que le
  propriétaire a enregistré (Compte → Clés API, fournisseur `youtube`) ;
- Instagram : l'access token du propriétaire (fournisseur `instagram`), publié sur la page
  de la chaîne, sinon sur la page par défaut enregistrée avec le token (`metadata.page_id`).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

from agent.core.api_keys import fetch_api_key

if TYPE_CHECKING:
    from agent.core.database import Channel


@dataclass(frozen=True)
class InstagramCredentials:
    access_token: str
    page_id: str


async def user_youtube_refresh_token(user_id: uuid.UUID) -> str | None:
    """Refresh token du compte Google enregistré par l'utilisateur."""
    return (await fetch_api_key(user_id, "youtube", purpose="youtube_publish")).key


async def youtube_refresh_token(channel: Channel) -> str | None:
    """Token OAuth de la chaîne, sinon celui du compte Google de son propriétaire."""
    if channel.youtube_refresh_token:
        return channel.youtube_refresh_token
    return await user_youtube_refresh_token(channel.user_id)


async def instagram_credentials(channel: Channel) -> InstagramCredentials | None:
    ctx = await fetch_api_key(channel.user_id, "instagram", purpose="instagram_publish")
    if not ctx.key:
        return None
    page_id = channel.instagram_page_id or str((ctx.metadata or {}).get("page_id") or "").strip()
    return InstagramCredentials(access_token=ctx.key, page_id=page_id) if page_id else None
