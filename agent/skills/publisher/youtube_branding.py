from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx

from agent.core.channel_brand import YouTubeBrand
from agent.core.config import settings

logger = logging.getLogger(__name__)

YOUTUBE_SCOPES = [
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"


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
    if not settings.youtube_client_id or not settings.youtube_client_secret:
        raise RuntimeError("YOUTUBE_CLIENT_ID et YOUTUBE_CLIENT_SECRET requis")

    params = {
        "client_id": settings.youtube_client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(YOUTUBE_SCOPES),
        "state": state,
        "access_type": "offline",
        "include_granted_scopes": "true",
        "prompt": "consent",
    }
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


def exchange_oauth_code(code: str, redirect_uri: str) -> str:
    if not settings.youtube_client_id or not settings.youtube_client_secret:
        raise RuntimeError("YOUTUBE_CLIENT_ID et YOUTUBE_CLIENT_SECRET requis")

    with httpx.Client() as client:
        token_resp = client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.youtube_client_id,
                "client_secret": settings.youtube_client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )
    if token_resp.status_code != 200:
        detail = token_resp.text.strip() or f"HTTP {token_resp.status_code}"
        raise RuntimeError(detail)

    refresh_token = token_resp.json().get("refresh_token")
    if not refresh_token:
        raise RuntimeError("Pas de refresh_token — révoquez l'accès et réessayez avec prompt=consent")
    return refresh_token


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


def _fetch_channel_branding(youtube: Any, youtube_channel_id: str) -> dict[str, Any]:
    response = youtube.channels().list(
        part="brandingSettings,snippet",
        id=youtube_channel_id,
    ).execute()
    items = response.get("items", [])
    if not items:
        raise RuntimeError(f"Chaîne YouTube introuvable : {youtube_channel_id}")
    return items[0]


def _merge_branding_settings(
    existing: dict[str, Any],
    *,
    channel: dict[str, Any] | None = None,
    image: dict[str, Any] | None = None,
) -> dict[str, Any]:
    branding = dict(existing.get("brandingSettings") or {})
    if channel is not None:
        merged_channel = dict(branding.get("channel") or {})
        merged_channel.update(channel)
        branding["channel"] = merged_channel
    if image is not None:
        merged_image = dict(branding.get("image") or {})
        merged_image.update(image)
        branding["image"] = merged_image
    return branding


def _update_branding_settings(
    youtube: Any,
    youtube_channel_id: str,
    existing_channel: dict[str, Any],
    *,
    channel: dict[str, Any] | None = None,
    image: dict[str, Any] | None = None,
) -> None:
    branding_settings = _merge_branding_settings(existing_channel, channel=channel, image=image)
    youtube.channels().update(
        part="brandingSettings",
        body={"id": youtube_channel_id, "brandingSettings": branding_settings},
    ).execute()


def _update_sync(youtube_channel_id: str, brand: YouTubeBrand, refresh_token: str | None) -> None:
    from googleapiclient.discovery import build

    youtube = build("youtube", "v3", credentials=_build_credentials(refresh_token))
    existing = _fetch_channel_branding(youtube, youtube_channel_id)
    existing_channel_branding = (existing.get("brandingSettings") or {}).get("channel") or {}
    current_title = existing_channel_branding.get("title") or existing.get("snippet", {}).get("title", "")

    if brand.title[:100] != current_title[:100]:
        logger.warning(
            "Titre YouTube non modifiable via l'API (actuel=%r, souhaité=%r) — description/mots-clés mis à jour",
            current_title,
            brand.title[:100],
        )

    channel_updates: dict[str, Any] = {
        "description": brand.description[:1000],
        "keywords": " ".join(brand.keywords)[:500],
    }
    if current_title:
        # L'API exige le titre actuel ou son omission ; l'omettre efface les autres champs channel.
        channel_updates["title"] = current_title[:100]
    if not existing_channel_branding.get("defaultLanguage"):
        channel_updates["defaultLanguage"] = "fr"

    _update_branding_settings(
        youtube,
        youtube_channel_id,
        existing,
        channel=channel_updates,
    )


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

    existing = _fetch_channel_branding(youtube, youtube_channel_id)
    _update_branding_settings(
        youtube,
        youtube_channel_id,
        existing,
        image={"bannerExternalUrl": banner_url},
    )


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
    existing = _fetch_channel_branding(youtube, youtube_channel_id)
    existing_channel_branding = (existing.get("brandingSettings") or {}).get("channel") or {}
    channel_updates: dict[str, Any] = {"unsubscribedTrailer": yt_video_id}
    current_title = existing_channel_branding.get("title") or existing.get("snippet", {}).get("title", "")
    if current_title:
        channel_updates["title"] = current_title[:100]
    _update_branding_settings(
        youtube,
        youtube_channel_id,
        existing,
        channel=channel_updates,
    )


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
