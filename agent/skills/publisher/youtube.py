from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


async def upload_video(
    video_path: Path,
    title: str,
    description: str,
    tags: list[str],
    category_id: str = "27",
    privacy_status: str = "public",
    made_for_kids: bool = False,
    contains_synthetic_media: bool = False,
    refresh_token: str | None = None,
) -> str:
    """Upload une vidéo sur YouTube via YouTube Data API v3. Retourne l'ID vidéo."""
    from agent.core.config import settings

    if not settings.youtube_client_id:
        raise RuntimeError("Identifiants YouTube non configurés dans .env")

    loop = __import__("asyncio").get_event_loop()
    video_id = await loop.run_in_executor(
        None,
        _upload_sync,
        video_path, title, description, tags, category_id, privacy_status, made_for_kids,
        contains_synthetic_media, refresh_token,
    )
    logger.info("YouTube upload réussi : https://youtube.com/watch?v=%s", video_id)
    return video_id


def _upload_sync(
    video_path: Path,
    title: str,
    description: str,
    tags: list[str],
    category_id: str,
    privacy_status: str,
    made_for_kids: bool,
    contains_synthetic_media: bool,
    refresh_token: str | None,
) -> str:
    from agent.core.config import settings
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    token = refresh_token or settings.youtube_refresh_token or None
    creds = Credentials(
        token=None,
        refresh_token=token,
        client_id=settings.youtube_client_id,
        client_secret=settings.youtube_client_secret,
        token_uri="https://oauth2.googleapis.com/token",
    )

    youtube = build("youtube", "v3", credentials=creds)

    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags,
            "categoryId": category_id,
        },
        "status": {
            "privacyStatus": privacy_status,
            "madeForKids": made_for_kids,
            "containsSyntheticMedia": contains_synthetic_media,
        },
    }

    media = MediaFileUpload(str(video_path), chunksize=-1, resumable=True)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    while response is None:
        _, response = request.next_chunk()

    return response["id"]


async def set_thumbnail(
    video_id: str,
    thumbnail_path: Path,
    refresh_token: str | None = None,
) -> None:
    """Upload une miniature personnalisée pour une vidéo YouTube."""
    loop = __import__("asyncio").get_event_loop()
    await loop.run_in_executor(None, _set_thumbnail_sync, video_id, thumbnail_path, refresh_token)


def _set_thumbnail_sync(video_id: str, thumbnail_path: Path, refresh_token: str | None) -> None:
    from agent.core.config import settings
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    token = refresh_token or settings.youtube_refresh_token
    creds = Credentials(
        token=None,
        refresh_token=token,
        client_id=settings.youtube_client_id,
        client_secret=settings.youtube_client_secret,
        token_uri="https://oauth2.googleapis.com/token",
    )
    youtube = build("youtube", "v3", credentials=creds)
    suffix = thumbnail_path.suffix.lstrip(".").lower() or "jpeg"
    media = MediaFileUpload(str(thumbnail_path), mimetype=f"image/{suffix}")
    youtube.thumbnails().set(videoId=video_id, media_body=media).execute()
    logger.info("Miniature définie pour la vidéo YouTube %s", video_id)
