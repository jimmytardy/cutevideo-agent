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


_CHANNEL_ID_RE = re.compile(r"^UC[\w-]{22}$")
_HANDLE_RE = re.compile(r"^@?[\w.-]+$")


def resolve_youtube_channel_id(handle_or_url: str) -> str | None:
    """Résout un handle (@foo), URL ou channel ID vers un channel ID YouTube."""
    raw = (handle_or_url or "").strip()
    if not raw:
        return None
    if _CHANNEL_ID_RE.match(raw):
        return raw
    if "youtube.com/channel/" in raw:
        part = raw.split("youtube.com/channel/", 1)[1].split("/")[0].split("?")[0]
        return part if _CHANNEL_ID_RE.match(part) else None
    if "youtube.com/@" in raw:
        handle = raw.split("youtube.com/@", 1)[1].split("/")[0].split("?")[0]
        return f"@{handle}" if handle else None
    if raw.startswith("@"):
        return raw
    if _HANDLE_RE.match(raw):
        return raw if raw.startswith("@") else f"@{raw}"
    return None


def _resolve_channel_id_sync(handle_or_url: str, refresh_token: str | None) -> str | None:
    from googleapiclient.discovery import build

    resolved = resolve_youtube_channel_id(handle_or_url)
    if not resolved:
        return None
    if _CHANNEL_ID_RE.match(resolved):
        return resolved

    creds = _build_credentials(refresh_token)
    youtube = build("youtube", "v3", credentials=creds)
    handle = resolved.lstrip("@")
    try:
        resp = (
            youtube.channels()
            .list(part="id", forHandle=handle)
            .execute()
        )
        items = resp.get("items", [])
        if items:
            return str(items[0].get("id", "")) or None
    except Exception as exc:
        if _is_invalid_grant(exc):
            raise YouTubeAuthError(str(exc)) from exc
        logger.warning("Résolution handle YouTube %s : %s", handle_or_url, exc)

    try:
        resp = (
            youtube.search()
            .list(part="snippet", q=resolved, type="channel", maxResults=1)
            .execute()
        )
        for item in resp.get("items", []):
            cid = item.get("id", {}).get("channelId")
            if cid:
                return str(cid)
    except YouTubeAuthError:
        raise
    except Exception as exc:
        logger.warning("Recherche chaîne YouTube %s : %s", handle_or_url, exc)
    return None


def _list_channel_top_videos_sync(
    channel_id: str,
    refresh_token: str | None,
    *,
    max_videos: int,
) -> list[dict[str, Any]]:
    from googleapiclient.discovery import build

    creds = _build_credentials(refresh_token)
    youtube = build("youtube", "v3", credentials=creds)

    ch_resp = (
        youtube.channels()
        .list(part="contentDetails", id=channel_id)
        .execute()
    )
    items = ch_resp.get("items", [])
    if not items:
        return []
    uploads_id = (
        items[0].get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads")
    )
    if not uploads_id:
        return []

    video_ids: list[str] = []
    page_token: str | None = None
    while len(video_ids) < max_videos:
        pl_resp = (
            youtube.playlistItems()
            .list(
                part="snippet",
                playlistId=uploads_id,
                maxResults=min(50, max_videos - len(video_ids)),
                pageToken=page_token,
            )
            .execute()
        )
        for item in pl_resp.get("items", []):
            vid = item.get("snippet", {}).get("resourceId", {}).get("videoId")
            if vid and vid not in video_ids:
                video_ids.append(vid)
        page_token = pl_resp.get("nextPageToken")
        if not page_token:
            break

    if not video_ids:
        return []

    vid_resp = (
        youtube.videos()
        .list(part="snippet,statistics,contentDetails", id=",".join(video_ids[:max_videos]))
        .execute()
    )
    videos: list[dict[str, Any]] = []
    for item in vid_resp.get("items", []):
        stats = item.get("statistics", {})
        snip = item.get("snippet", {})
        vid_id = item.get("id", "")
        videos.append(
            {
                "video_id": vid_id,
                "title": snip.get("title", ""),
                "channel_id": snip.get("channelId", channel_id),
                "channel_title": snip.get("channelTitle", ""),
                "view_count": int(stats.get("viewCount", 0) or 0),
                "like_count": int(stats.get("likeCount", 0) or 0),
                "published_at": snip.get("publishedAt", ""),
                "url": f"https://www.youtube.com/watch?v={vid_id}",
                "duration_iso": item.get("contentDetails", {}).get("duration", ""),
            }
        )
    videos.sort(key=lambda v: v.get("view_count", 0), reverse=True)
    return videos[:max_videos]


async def list_channel_top_videos(
    handle_or_url: str,
    refresh_token: str | None = None,
    *,
    max_videos: int = 5,
) -> list[dict[str, Any]]:
    """Liste les vidéos les plus vues d'une chaîne YouTube (handle, URL ou ID)."""
    import asyncio
    import functools

    channel_id = await asyncio.get_event_loop().run_in_executor(
        None,
        functools.partial(_resolve_channel_id_sync, handle_or_url, refresh_token),
    )
    if not channel_id:
        return []

    fn = functools.partial(
        _list_channel_top_videos_sync,
        channel_id,
        refresh_token,
        max_videos=max_videos,
    )
    return await asyncio.get_event_loop().run_in_executor(None, fn)
