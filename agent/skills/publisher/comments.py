"""Lecture et réponse aux commentaires publics des vidéos publiées.

YouTube Data API (scope `youtube.force-ssl`, déjà demandé par l'OAuth de la chaîne), Instagram Graph API
(permission `instagram_manage_comments` sur le token du propriétaire) et TikTok via Zernio — seul
fournisseur TikTok avec une API commentaires, Composio et Post for Me n'en ont pas (`client_for()` → None).

Le texte des commentaires est une donnée non fiable : il n'est jamais interprété ici, seulement remis
tel quel à `agent/agents/comment_reply_agent.py`, qui le balise avant de l'envoyer au LLM.
Les journaux ne contiennent que des identifiants, jamais de token.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, UTC
from typing import TYPE_CHECKING, Any, Protocol

import aiohttp

from agent.skills.publisher import credentials
from agent.skills.publisher.graph_api import graph_api_url
from agent.skills.publisher.instagram import graph_get, graph_post
from agent.skills.publisher.tiktok_providers import ZernioPublisher, supports_comments
from agent.skills.publisher.youtube_branding import build_youtube_credentials

if TYPE_CHECKING:
    from agent.core.database import Channel

# Délai minimal entre deux lectures des commentaires d'une même publication (0 = à chaque passage).
# Zernio met la liste en cache 10 min et demande de ne pas la sonder plus souvent.
POLL_INTERVAL_S: dict[str, int] = {"youtube": 0, "instagram": 0, "tiktok": 600}

# Longueur maximale d'une réponse par plateforme (TikTok : 150 caractères par commentaire).
DEFAULT_REPLY_MAX_CHARS = 500
REPLY_MAX_CHARS: dict[str, int] = {"youtube": 500, "instagram": 500, "tiktok": 150}

HTTP_TIMEOUT_S = 30.0


@dataclass(frozen=True)
class PlatformComment:
    platform_comment_id: str
    author_name: str
    author_id: str
    text: str
    created_at: datetime | None
    is_owner: bool  # écrit par la chaîne elle-même
    has_owner_reply: bool  # la chaîne y a déjà répondu (à la main ou par l'agent)


class CommentClient(Protocol):
    platform: str

    async def list_comments(self, channel: Channel, platform_video_id: str) -> list[PlatformComment]:
        """Commentaires de premier niveau de la vidéo (les plus récents d'abord ou dans l'ordre de l'API)."""

    async def reply(self, channel: Channel, platform_video_id: str, comment_id: str, text: str) -> str:
        """Publie une réponse ; renvoie l'id de la réponse ("" si la plateforme ne le donne pas)."""


def parse_platform_timestamp(value: Any) -> datetime | None:
    """ISO 8601 (« Z », « +00:00 » ou « +0000 »), epoch en secondes ou millisecondes ; None si illisible."""
    if value is None or value == "" or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        seconds = float(value) / 1000 if value > 1e11 else float(value)
        try:
            return datetime.fromtimestamp(seconds, UTC)
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value).strip()
    if text.isdigit():
        return parse_platform_timestamp(int(text))
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    elif len(text) > 5 and text[-5] in "+-" and text[-5:][1:].isdigit():
        text = f"{text[:-2]}:{text[-2:]}"  # +0000 → +00:00
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


# ── YouTube ──────────────────────────────────────────────────────────────────


def _youtube_author(comment: dict[str, Any]) -> str:
    snippet = comment.get("snippet") or {}
    return str((snippet.get("authorChannelId") or {}).get("value") or "")


def _youtube_list_sync(refresh_token: str, video_id: str, owner_channel_id: str) -> list[PlatformComment]:
    from googleapiclient.discovery import build

    youtube = build("youtube", "v3", credentials=build_youtube_credentials(refresh_token))
    owner = owner_channel_id
    if not owner:  # chaîne connectée par un token de compte sans `youtube_channel_id`
        items = youtube.channels().list(part="id", mine=True).execute().get("items") or []
        owner = str(items[0].get("id") or "") if items else ""
    response = youtube.commentThreads().list(
        part="snippet,replies", videoId=video_id, order="time", maxResults=100, textFormat="plainText"
    ).execute()
    comments: list[PlatformComment] = []
    for item in response.get("items") or []:
        top = (item.get("snippet") or {}).get("topLevelComment") or {}
        snippet = top.get("snippet") or {}
        author_id = _youtube_author(top)
        replies = (item.get("replies") or {}).get("comments") or []
        comments.append(
            PlatformComment(
                platform_comment_id=str(top.get("id") or item.get("id") or ""),
                author_name=str(snippet.get("authorDisplayName") or ""),
                author_id=author_id,
                text=str(snippet.get("textOriginal") or snippet.get("textDisplay") or ""),
                created_at=parse_platform_timestamp(snippet.get("publishedAt")),
                is_owner=bool(owner) and author_id == owner,
                has_owner_reply=bool(owner) and any(_youtube_author(r) == owner for r in replies),
            )
        )
    return comments


def _youtube_reply_sync(refresh_token: str, parent_id: str, text: str) -> str:
    from googleapiclient.discovery import build

    youtube = build("youtube", "v3", credentials=build_youtube_credentials(refresh_token))
    response = youtube.comments().insert(
        part="snippet", body={"snippet": {"parentId": parent_id, "textOriginal": text}}
    ).execute()
    return str(response.get("id") or "")


async def _youtube_token(channel: Channel) -> str:
    token = await credentials.youtube_refresh_token(channel)
    if not token:
        raise RuntimeError("Token YouTube manquant — connectez la chaîne via OAuth")
    return token


class YouTubeComments:
    platform = "youtube"

    async def list_comments(self, channel: Channel, platform_video_id: str) -> list[PlatformComment]:
        token = await _youtube_token(channel)
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, _youtube_list_sync, token, platform_video_id, channel.youtube_channel_id or ""
        )

    async def reply(self, channel: Channel, platform_video_id: str, comment_id: str, text: str) -> str:
        token = await _youtube_token(channel)
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _youtube_reply_sync, token, comment_id, text)


# ── Instagram ────────────────────────────────────────────────────────────────


async def _instagram_credentials(channel: Channel) -> credentials.InstagramCredentials:
    creds = await credentials.instagram_credentials(channel)
    if creds is None:
        raise RuntimeError("Token Instagram ou identifiant de compte manquant (Compte → Clés API)")
    return creds


class InstagramComments:
    platform = "instagram"

    async def list_comments(self, channel: Channel, platform_video_id: str) -> list[PlatformComment]:
        creds = await _instagram_credentials(channel)
        owner_username = str((channel.instagram_profile or {}).get("username") or "")
        params = {
            "fields": "id,text,username,from{id,username},timestamp,replies{id,from{id}}",
            "limit": "50",
            "access_token": creds.access_token,
        }
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=HTTP_TIMEOUT_S)) as session:
            data = await graph_get(session, graph_api_url(f"{platform_video_id}/comments"), params)
        comments: list[PlatformComment] = []
        for item in data.get("data") or []:
            sender = item.get("from") or {}
            author_id = str(sender.get("id") or "")
            username = str(sender.get("username") or item.get("username") or "")
            # `from` n'est pas toujours renvoyé : repli sur le nom d'utilisateur du profil connecté.
            is_owner = author_id == creds.page_id if author_id else bool(owner_username) and username == owner_username
            replies = (item.get("replies") or {}).get("data") or []
            comments.append(
                PlatformComment(
                    platform_comment_id=str(item.get("id") or ""),
                    author_name=username,
                    author_id=author_id,
                    text=str(item.get("text") or ""),
                    created_at=parse_platform_timestamp(item.get("timestamp")),
                    is_owner=is_owner,
                    has_owner_reply=any(str((r.get("from") or {}).get("id") or "") == creds.page_id for r in replies),
                )
            )
        return comments

    async def reply(self, channel: Channel, platform_video_id: str, comment_id: str, text: str) -> str:
        creds = await _instagram_credentials(channel)
        params = {"message": text, "access_token": creds.access_token}
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=HTTP_TIMEOUT_S)) as session:
            reply_id = await graph_post(session, graph_api_url(f"{comment_id}/replies"), params, step="réponse au commentaire")
        if not reply_id:
            raise RuntimeError("Instagram : réponse au commentaire refusée (détail dans le journal)")
        return reply_id


# ── TikTok (Zernio) ──────────────────────────────────────────────────────────


class TikTokComments:
    platform = "tiktok"

    def __init__(self) -> None:
        self._zernio = ZernioPublisher()

    async def list_comments(self, channel: Channel, platform_video_id: str) -> list[PlatformComment]:
        comments: list[PlatformComment] = []
        for item in await self._zernio.list_comments(channel, platform_video_id):
            if item.get("canReply") is False:
                continue
            sender = item.get("from") or {}
            replies = [r for r in item.get("replies") or [] if isinstance(r, dict)]
            comments.append(
                PlatformComment(
                    platform_comment_id=str(item.get("id") or ""),
                    author_name=str(sender.get("name") or sender.get("username") or ""),
                    author_id=str(sender.get("id") or ""),
                    text=str(item.get("message") or ""),
                    created_at=parse_platform_timestamp(item.get("createdTime")),
                    is_owner=bool(sender.get("isOwner")),
                    has_owner_reply=any(bool((r.get("from") or {}).get("isOwner")) for r in replies),
                )
            )
        return comments

    async def reply(self, channel: Channel, platform_video_id: str, comment_id: str, text: str) -> str:
        return await self._zernio.reply_comment(channel, platform_video_id, comment_id, text)


def client_for(channel: Channel, platform: str, provider: str | None = None) -> CommentClient | None:
    """Client de la plateforme d'une publication (`provider` = `Publication.provider`) ; None quand le
    fournisseur qui a publié ne permet pas les commentaires."""
    if platform == "youtube":
        return YouTubeComments()
    if platform == "instagram":
        return InstagramComments()
    if platform == "tiktok" and supports_comments(channel, provider):
        return TikTokComments()
    return None
