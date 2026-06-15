from __future__ import annotations

import logging
from typing import Literal

import aiohttp

from agent.core.config import settings

logger = logging.getLogger(__name__)

API_URL = "https://pixabay.com/api/"
MediaType = Literal["image", "video"]


async def search(
    keywords: list[str],
    period: str = "",
    *,
    media_type: MediaType = "image",
) -> list[dict]:
    """Recherche sur Pixabay — photos ou vidéos libres de droits."""
    if not settings.pixabay_api_key:
        logger.debug("Pixabay API key non configurée, skip")
        return []

    query = " ".join(keywords[:3])
    if media_type == "video":
        return await _search_videos(query)
    return await _search_photos(query)


async def _search_photos(query: str) -> list[dict]:
    params = {
        "key": settings.pixabay_api_key,
        "q": query,
        "image_type": "photo",
        "orientation": "horizontal",
        "per_page": 10,
        "safesearch": "true",
    }

    results: list[dict] = []
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                API_URL, params=params, timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                if resp.status != 200:
                    logger.warning("Pixabay photos HTTP %d pour %r", resp.status, query)
                    return []
                data = await resp.json()

        for hit in data.get("hits", []):
            url = hit.get("largeImageURL") or hit.get("webformatURL")
            if not url:
                continue
            user = hit.get("user", "Pixabay")
            results.append({
                "source": "pixabay",
                "url": url,
                "license": "Pixabay License (libre d'utilisation)",
                "attribution": f"Image par {user} sur Pixabay",
                "title": hit.get("tags") or query,
                "width": hit.get("imageWidth"),
                "asset_type": "image",
            })
    except Exception as exc:
        logger.warning("Pixabay photos search error: %s", exc)

    return results


async def _search_videos(query: str) -> list[dict]:
    params = {
        "key": settings.pixabay_api_key,
        "q": query,
        "video_type": "film",
        "orientation": "horizontal",
        "per_page": 10,
        "safesearch": "true",
    }

    results: list[dict] = []
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                API_URL, params=params, timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                if resp.status != 200:
                    logger.warning("Pixabay videos HTTP %d pour %r", resp.status, query)
                    return []
                data = await resp.json()

        for hit in data.get("hits", []):
            videos = hit.get("videos") or {}
            large = videos.get("large") or videos.get("medium") or videos.get("small") or {}
            url = large.get("url")
            if not url:
                continue
            user = hit.get("user", "Pixabay")
            results.append({
                "source": "pixabay",
                "url": url,
                "thumbnail_url": f"https://i.vimeocdn.com/video/{hit.get('picture_id')}_640.jpg"
                if hit.get("picture_id")
                else None,
                "license": "Pixabay License (libre d'utilisation)",
                "attribution": f"Vidéo par {user} sur Pixabay",
                "title": hit.get("tags") or query,
                "width": large.get("width"),
                "duration_s": hit.get("duration"),
                "asset_type": "video",
            })
    except Exception as exc:
        logger.warning("Pixabay videos search error: %s", exc)

    return results
