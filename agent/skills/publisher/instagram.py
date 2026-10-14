from __future__ import annotations

import logging
from pathlib import Path

import aiohttp

logger = logging.getLogger(__name__)

GRAPH_API_URL = "https://graph.facebook.com/v19.0"


async def upload_reel(
    video_path: Path,
    caption: str,
    hashtags: list[str],
    video_url: str,
    page_id: str,
    access_token: str,
) -> str | None:
    """Publie un Reel Instagram via Graph API avec le token du propriétaire. Retourne l'ID du media."""
    if not access_token or not page_id:
        raise RuntimeError("Credentials Instagram non configurés")

    full_caption = f"{caption}\n\n{' '.join('#' + h for h in hashtags)}"

    container_id = await _create_container(video_url, full_caption, page_id, access_token)
    if not container_id:
        return None

    published_id = await _publish_container(container_id, page_id, access_token)
    logger.info("Instagram Reel publié : %s", published_id)
    return published_id


async def _create_container(video_url: str, caption: str, page_id: str, access_token: str) -> str | None:
    url = f"{GRAPH_API_URL}/{page_id}/media"
    params = {
        "media_type": "REELS",
        "video_url": video_url,
        "caption": caption,
        "access_token": access_token,
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(url, data=params, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            data = await resp.json()
            return data.get("id")


async def _publish_container(container_id: str, page_id: str, access_token: str) -> str | None:
    url = f"{GRAPH_API_URL}/{page_id}/media_publish"
    params = {
        "creation_id": container_id,
        "access_token": access_token,
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(url, data=params, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            data = await resp.json()
            return data.get("id")
