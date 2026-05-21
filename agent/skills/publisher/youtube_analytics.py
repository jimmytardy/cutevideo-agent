from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def fetch_video_metrics(
    video_id: str,
    refresh_token: str | None = None,
) -> dict[str, Any]:
    """Récupère les statistiques publiques d'une vidéo YouTube."""
    loop = __import__("asyncio").get_event_loop()
    return await loop.run_in_executor(
        None, _fetch_sync, video_id, refresh_token
    )


def _fetch_sync(video_id: str, refresh_token: str | None) -> dict[str, Any]:
    from agent.core.config import settings
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    if not settings.youtube_client_id:
        raise RuntimeError("Identifiants YouTube non configurés dans .env")

    token = refresh_token or settings.youtube_refresh_token or None
    creds = Credentials(
        token=None,
        refresh_token=token,
        client_id=settings.youtube_client_id,
        client_secret=settings.youtube_client_secret,
        token_uri="https://oauth2.googleapis.com/token",
    )
    youtube = build("youtube", "v3", credentials=creds)
    response = (
        youtube.videos()
        .list(part="statistics,snippet", id=video_id)
        .execute()
    )
    items = response.get("items", [])
    if not items:
        return {"video_id": video_id, "error": "video_not_found"}

    item = items[0]
    stats = item.get("statistics", {})
    snippet = item.get("snippet", {})
    return {
        "video_id": video_id,
        "title": snippet.get("title"),
        "published_at": snippet.get("publishedAt"),
        "views": int(stats.get("viewCount", 0)),
        "likes": int(stats.get("likeCount", 0)),
        "comments": int(stats.get("commentCount", 0)),
        "raw_statistics": stats,
    }
