from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


def search_queries_from_prompt(prompt: str, *, max_queries: int = 4) -> list[str]:
    """Dérive des requêtes YouTube à partir de l'idée utilisateur."""
    cleaned = re.sub(r"\s+", " ", prompt.strip())[:200]
    if not cleaned:
        return ["documentaire éducatif français"]
    queries = [cleaned]
    if "français" not in cleaned.lower() and "france" not in cleaned.lower():
        queries.append(f"{cleaned} documentaire français")
    queries.append(f"{cleaned} youtube")
    words = cleaned.split()[:6]
    if len(words) >= 3:
        queries.append(" ".join(words[:4]))
    seen: set[str] = set()
    unique: list[str] = []
    for q in queries:
        key = q.lower()
        if key not in seen:
            seen.add(key)
            unique.append(q)
    return unique[:max_queries]


def _build_credentials(refresh_token: str | None) -> Any:
    from agent.core.config import settings
    from google.oauth2.credentials import Credentials

    token = refresh_token or settings.youtube_refresh_token or None
    if not token:
        raise RuntimeError(
            "Token YouTube manquant — configurez YOUTUBE_REFRESH_TOKEN pour l'analyse marché"
        )
    return Credentials(
        token=None,
        refresh_token=token,
        client_id=settings.youtube_client_id,
        client_secret=settings.youtube_client_secret,
        token_uri="https://oauth2.googleapis.com/token",
    )


class YouTubeAuthError(RuntimeError):
    """Le refresh token YouTube est invalide ou révoqué."""


def _is_invalid_grant(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "invalid_grant" in msg or "token has been expired or revoked" in msg


def _discover_sync(
    queries: list[str],
    refresh_token: str | None,
    *,
    max_channels: int,
    max_videos: int,
    region_code: str,
    relevance_language: str,
) -> dict[str, Any]:
    from googleapiclient.discovery import build

    creds = _build_credentials(refresh_token)
    youtube = build("youtube", "v3", credentials=creds)

    channel_ids: list[str] = []
    video_ids: list[str] = []
    channel_snippets: dict[str, dict[str, Any]] = {}
    video_snippets: dict[str, dict[str, Any]] = {}

    for query in queries:
        try:
            ch_resp = (
                youtube.search()
                .list(
                    part="snippet",
                    q=query,
                    type="channel",
                    maxResults=min(8, max_channels),
                    regionCode=region_code,
                    relevanceLanguage=relevance_language,
                )
                .execute()
            )
            for item in ch_resp.get("items", []):
                cid = item.get("id", {}).get("channelId")
                if cid and cid not in channel_ids:
                    channel_ids.append(cid)
                    channel_snippets[cid] = item.get("snippet", {})
        except Exception as e:
            if _is_invalid_grant(e):
                raise YouTubeAuthError(
                    "Le refresh token YouTube est expiré ou révoqué (invalid_grant). "
                    "Regénère YOUTUBE_REFRESH_TOKEN via le flow OAuth2 Google."
                ) from e
            logger.warning("Recherche chaînes YouTube (%s) : %s", query, e)

        try:
            vid_resp = (
                youtube.search()
                .list(
                    part="snippet",
                    q=query,
                    type="video",
                    maxResults=min(10, max_videos),
                    order="viewCount",
                    regionCode=region_code,
                    relevanceLanguage=relevance_language,
                )
                .execute()
            )
            for item in vid_resp.get("items", []):
                vid = item.get("id", {}).get("videoId")
                if vid and vid not in video_ids:
                    video_ids.append(vid)
                    video_snippets[vid] = item.get("snippet", {})
                    ch_id = item.get("snippet", {}).get("channelId")
                    if ch_id and ch_id not in channel_ids:
                        channel_ids.append(ch_id)
        except YouTubeAuthError:
            raise
        except Exception as e:
            logger.warning("Recherche vidéos YouTube (%s) : %s", query, e)

    channel_ids = channel_ids[:max_channels]
    video_ids = video_ids[:max_videos]

    channels: list[dict[str, Any]] = []
    if channel_ids:
        stats_resp = (
            youtube.channels()
            .list(part="snippet,statistics", id=",".join(channel_ids))
            .execute()
        )
        for item in stats_resp.get("items", []):
            cid = item.get("id", "")
            stats = item.get("statistics", {})
            snip = item.get("snippet", {})
            channels.append(
                {
                    "channel_id": cid,
                    "title": snip.get("title", ""),
                    "description": (snip.get("description") or "")[:400],
                    "custom_url": snip.get("customUrl", ""),
                    "subscriber_count": int(stats.get("subscriberCount", 0) or 0),
                    "video_count": int(stats.get("videoCount", 0) or 0),
                    "view_count": int(stats.get("viewCount", 0) or 0),
                    "country": snip.get("country", ""),
                }
            )

    videos: list[dict[str, Any]] = []
    if video_ids:
        vid_resp = (
            youtube.videos()
            .list(part="snippet,statistics", id=",".join(video_ids))
            .execute()
        )
        for item in vid_resp.get("items", []):
            stats = item.get("statistics", {})
            snip = item.get("snippet", {})
            videos.append(
                {
                    "video_id": item.get("id", ""),
                    "title": snip.get("title", ""),
                    "channel_title": snip.get("channelTitle", ""),
                    "channel_id": snip.get("channelId", ""),
                    "view_count": int(stats.get("viewCount", 0) or 0),
                    "like_count": int(stats.get("likeCount", 0) or 0),
                    "published_at": snip.get("publishedAt", ""),
                }
            )

    channels.sort(key=lambda c: c.get("subscriber_count", 0), reverse=True)
    videos.sort(key=lambda v: v.get("view_count", 0), reverse=True)

    return {
        "queries_used": queries,
        "channels": channels,
        "top_videos": videos,
        "region_code": region_code,
        "relevance_language": relevance_language,
    }


async def discover_youtube_landscape(
    prompt: str,
    refresh_token: str | None = None,
    *,
    max_channels: int = 10,
    max_videos: int = 15,
    region_code: str = "FR",
    relevance_language: str = "fr",
) -> dict[str, Any]:
    """Collecte chaînes et vidéos concurrentes via YouTube Data API."""
    import asyncio
    import functools

    queries = search_queries_from_prompt(prompt)
    fn = functools.partial(
        _discover_sync,
        queries,
        refresh_token,
        max_channels=max_channels,
        max_videos=max_videos,
        region_code=region_code,
        relevance_language=relevance_language,
    )
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, fn)
