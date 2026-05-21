from __future__ import annotations

import logging
from pathlib import Path

import aiohttp

from agent.core.config import settings

logger = logging.getLogger(__name__)

GRAPH_API_URL = "https://graph.facebook.com/v19.0"


async def upload_reel(
    video_path: Path,
    caption: str,
    hashtags: list[str],
    video_url: str,
    page_id: str | None = None,
) -> str | None:
    """Publie un Reel Instagram via Graph API. Retourne l'ID du media."""
    ig_page = page_id or settings.instagram_page_id
    if not settings.instagram_access_token or not ig_page:
        raise RuntimeError("Credentials Instagram non configurés")

    full_caption = f"{caption}\n\n{' '.join('#' + h for h in hashtags)}"

    container_id = await _create_container(video_url, full_caption, ig_page)
    if not container_id:
        return None

    published_id = await _publish_container(container_id, ig_page)
    logger.info("Instagram Reel publié : %s", published_id)
    return published_id


async def _create_container(video_url: str, caption: str, page_id: str) -> str | None:
    url = f"{GRAPH_API_URL}/{page_id}/media"
    params = {
        "media_type": "REELS",
        "video_url": video_url,
        "caption": caption,
        "access_token": settings.instagram_access_token,
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(url, data=params, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            data = await resp.json()
            return data.get("id")


async def _publish_container(container_id: str, page_id: str) -> str | None:
    url = f"{GRAPH_API_URL}/{page_id}/media_publish"
    params = {
        "creation_id": container_id,
        "access_token": settings.instagram_access_token,
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(url, data=params, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            data = await resp.json()
            return data.get("id")
