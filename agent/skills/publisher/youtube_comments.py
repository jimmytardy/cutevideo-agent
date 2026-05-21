from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class FetchedComment:
    platform_comment_id: str
    author_name: str
    text: str
    published_at: datetime | None
    parent_id: str | None = None


async def fetch_video_comments(
    video_id: str,
    refresh_token: str | None = None,
    max_results: int = 50,
) -> list[FetchedComment]:
    loop = __import__("asyncio").get_event_loop()
    return await loop.run_in_executor(
        None, _fetch_sync, video_id, refresh_token, max_results
    )


async def reply_to_comment(
    parent_id: str,
    reply_text: str,
    refresh_token: str | None = None,
) -> str:
    loop = __import__("asyncio").get_event_loop()
    return await loop.run_in_executor(
        None, _reply_sync, parent_id, reply_text, refresh_token
    )


def _fetch_sync(
    video_id: str,
    refresh_token: str | None,
    max_results: int,
) -> list[FetchedComment]:
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
        youtube.commentThreads()
        .list(
            part="snippet",
            videoId=video_id,
            maxResults=min(max_results, 100),
            order="time",
            textFormat="plainText",
        )
        .execute()
    )

    comments: list[FetchedComment] = []
    for thread in response.get("items", []):
        top = thread.get("snippet", {}).get("topLevelComment", {})
        snippet = top.get("snippet", {})
        published = snippet.get("publishedAt")
        published_dt = None
        if published:
            published_dt = datetime.fromisoformat(published.replace("Z", "+00:00"))
        comments.append(
            FetchedComment(
                platform_comment_id=top.get("id", thread.get("id", "")),
                author_name=snippet.get("authorDisplayName", ""),
                text=snippet.get("textDisplay", ""),
                published_at=published_dt,
                parent_id=top.get("id"),
            )
        )
    return comments


def _reply_sync(
    parent_id: str,
    reply_text: str,
    refresh_token: str | None,
) -> str:
    from agent.core.config import settings
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    token = refresh_token or settings.youtube_refresh_token or None
    creds = Credentials(
        token=None,
        refresh_token=token,
        client_id=settings.youtube_client_id,
        client_secret=settings.youtube_client_secret,
        token_uri="https://oauth2.googleapis.com/token",
    )
    youtube = build("youtube", "v3", credentials=creds)
    body: dict[str, Any] = {"snippet": {"parentId": parent_id, "textOriginal": reply_text}}
    response = youtube.comments().insert(part="snippet", body=body).execute()
    return response.get("id", "")
