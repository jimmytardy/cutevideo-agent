"""Identifiants de publication d'une chaîne.

`YOUTUBE_REFRESH_TOKEN` et `INSTAGRAM_ACCESS_TOKEN` (.env) donnent accès aux comptes
de l'exploitant : ils ne servent de repli qu'aux chaînes d'un administrateur. Une
chaîne d'un autre utilisateur publie uniquement avec son propre OAuth, sinon elle
pourrait uploader sur les comptes de l'exploitant.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from agent.core.config import settings
from agent.core.database import AsyncSessionFactory, User

if TYPE_CHECKING:
    from agent.core.database import Channel


async def channel_owner_is_admin(channel: Channel) -> bool:
    async with AsyncSessionFactory() as session:
        return bool(await session.scalar(select(User.is_admin).where(User.id == channel.user_id)))


async def youtube_refresh_token(channel: Channel) -> str | None:
    """Token OAuth de la chaîne, ou le token global si la chaîne appartient à un admin."""
    if channel.youtube_refresh_token:
        return channel.youtube_refresh_token
    if settings.youtube_refresh_token and await channel_owner_is_admin(channel):
        return settings.youtube_refresh_token
    return None


async def instagram_publishing_allowed(channel: Channel) -> bool:
    """Instagram n'a qu'un token global (pas d'OAuth par chaîne) : réservé aux chaînes admin."""
    return bool(settings.instagram_access_token) and await channel_owner_is_admin(channel)
