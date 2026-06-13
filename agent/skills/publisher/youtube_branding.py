from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from agent.core.channel_brand import YouTubeBrand
from agent.core.config import settings

logger = logging.getLogger(__name__)

YOUTUBE_SCOPES = [
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]


def _build_credentials(refresh_token: str | None = None) -> Any:
    from google.oauth2.credentials import Credentials

    token = refresh_token or settings.youtube_refresh_token or None
    if not token:
        raise RuntimeError("Token YouTube manquant — configurez YOUTUBE_REFRESH_TOKEN ou OAuth par chaîne")
    return Credentials(
        token=None,
        refresh_token=token,
        client_id=settings.youtube_client_id,
        client_secret=settings.youtube_client_secret,
        token_uri="https://oauth2.googleapis.com/token",
    )


def get_oauth_authorization_url(state: str, redirect_uri: str) -> str:
    from google_auth_oauthlib.flow import Flow

    if not settings.youtube_client_id or not settings.youtube_client_secret:
        raise RuntimeError("YOUTUBE_CLIENT_ID et YOUTUBE_CLIENT_SECRET requis")

    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": settings.youtube_client_id,
                "client_secret": settings.youtube_client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [redirect_uri],
            }
        },
        scopes=YOUTUBE_SCOPES,
        redirect_uri=redirect_uri,
    )
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
        state=state,
    )
    return auth_url


def exchange_oauth_code(code: str, redirect_uri: str) -> str:
    from google_auth_oauthlib.flow import Flow

    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": settings.youtube_client_id,
                "client_secret": settings.youtube_client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [redirect_uri],
            }
        },
        scopes=YOUTUBE_SCOPES,
        redirect_uri=redirect_uri,
    )
    flow.fetch_token(code=code)
    if not flow.credentials.refresh_token:
        raise RuntimeError("Pas de refresh_token — révoquez l'accès et réessayez avec prompt=consent")
    return flow.credentials.refresh_token


def _list_sync(refresh_token: str | None) -> list[dict[str, str]]:
    from googleapiclient.discovery import build

    youtube = build("youtube", "v3", credentials=_build_credentials(refresh_token))
    request = youtube.channels().list(part="snippet", mine=True, maxResults=50)
    response = request.execute()
    channels: list[dict[str, str]] = []
    for item in response.get("items", []):
        snippet = item.get("snippet", {})
        channels.append(
            {
                "channel_id": item["id"],
                "title": snippet.get("title", ""),
                "description": snippet.get("description", "")[:200],
                "custom_url": snippet.get("customUrl", ""),
            }
        )
    return channels


async def list_youtube_channels(refresh_token: str | None = None) -> list[dict[str, str]]:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _list_sync, refresh_token)


def _update_sync(youtube_channel_id: str, brand: YouTubeBrand, refresh_token: str | None) -> None:
    from googleapiclient.discovery import build

    youtube = build("youtube", "v3", credentials=_build_credentials(refresh_token))
    body = {
        "id": youtube_channel_id,
        "snippet": {
            "title": brand.title[:100],
            "description": brand.description[:1000],
            "defaultLanguage": "fr",
        },
        "brandingSettings": {
            "channel": {
                "title": brand.title[:100],
                "description": brand.description[:1000],
                "keywords": " ".join(brand.keywords)[:500],
            }
        },
    }
    youtube.channels().update(part="snippet,brandingSettings", body=body).execute()


async def update_channel_branding(
    youtube_channel_id: str,
    brand: YouTubeBrand,
    refresh_token: str | None = None,
) -> None:
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _update_sync, youtube_channel_id, brand, refresh_token)


# ── Banner ────────────────────────────────────────────────────────────────────

def _upload_banner_sync(image_path: Path, youtube_channel_id: str, refresh_token: str | None) -> None:
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    youtube = build("youtube", "v3", credentials=_build_credentials(refresh_token))

    media = MediaFileUpload(str(image_path), mimetype="image/png", resumable=False)
    banner_response = youtube.channelBanners().insert(
        part="snippet", body={}, media_body=media
    ).execute()

    banner_url = banner_response.get("url", "")
    if not banner_url:
        raise RuntimeError("Pas d'URL retournée par channelBanners.insert")

    youtube.channels().update(
        part="brandingSettings",
        body={
            "id": youtube_channel_id,
            "brandingSettings": {"image": {"bannerExternalUrl": banner_url}},
        },
    ).execute()


async def upload_channel_banner(
    image_path: Path,
    youtube_channel_id: str,
    refresh_token: str | None = None,
) -> None:
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _upload_banner_sync, image_path, youtube_channel_id, refresh_token)


# ── Trailer ───────────────────────────────────────────────────────────────────

def _set_trailer_sync(youtube_channel_id: str, yt_video_id: str, refresh_token: str | None) -> None:
    from googleapiclient.discovery import build

    youtube = build("youtube", "v3", credentials=_build_credentials(refresh_token))
    youtube.channels().update(
        part="brandingSettings",
        body={
            "id": youtube_channel_id,
            "brandingSettings": {"channel": {"unsubscribedTrailer": yt_video_id}},
        },
    ).execute()


async def set_channel_trailer(
    youtube_channel_id: str,
    yt_video_id: str,
    refresh_token: str | None = None,
) -> None:
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _set_trailer_sync, youtube_channel_id, yt_video_id, refresh_token)


# ── Playlists ─────────────────────────────────────────────────────────────────

def _create_playlist_sync(title: str, description: str, refresh_token: str | None) -> str:
    from googleapiclient.discovery import build

    youtube = build("youtube", "v3", credentials=_build_credentials(refresh_token))
    response = youtube.playlists().insert(
        part="snippet,status",
        body={
            "snippet": {
                "title": title[:100],
                "description": description[:5000],
                "defaultLanguage": "fr",
            },
            "status": {"privacyStatus": "public"},
        },
    ).execute()
    return response["id"]


async def create_playlist(
    title: str,
    description: str,
    refresh_token: str | None = None,
) -> str:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _create_playlist_sync, title, description, refresh_token)


def _add_to_playlist_sync(playlist_id: str, yt_video_id: str, refresh_token: str | None) -> None:
    from googleapiclient.discovery import build

    youtube = build("youtube", "v3", credentials=_build_credentials(refresh_token))
    youtube.playlistItems().insert(
        part="snippet",
        body={
            "snippet": {
                "playlistId": playlist_id,
                "resourceId": {"kind": "youtube#video", "videoId": yt_video_id},
            }
        },
    ).execute()


async def add_video_to_playlist(
    playlist_id: str,
    yt_video_id: str,
    refresh_token: str | None = None,
) -> None:
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _add_to_playlist_sync, playlist_id, yt_video_id, refresh_token)
