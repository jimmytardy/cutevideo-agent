from __future__ import annotations

import logging
from typing import Literal

import aiohttp

from agent.core.config import settings

logger = logging.getLogger(__name__)

PHOTOS_API_URL = "https://api.pexels.com/v1/search"
VIDEOS_API_URL = "https://api.pexels.com/videos/search"
MediaType = Literal["image", "video"]


async def search(
    keywords: list[str],
    period: str = "",
    *,
    media_type: MediaType = "image",
) -> list[dict]:
    """Recherche sur Pexels — photos et/ou vidéos libres."""
    if not settings.pexels_api_key:
        logger.debug("Pexels API key non configurée, skip")
        return []

    query = " ".join(keywords[:3])
    if media_type == "video":
        return await _search_videos(query)
    return await _search_photos(query)


async def _search_photos(query: str) -> list[dict]:
    headers = {"Authorization": settings.pexels_api_key}
    params = {
        "query": query,
        "per_page": "10",
        "orientation": "landscape",
    }

    results: list[dict] = []
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                PHOTOS_API_URL,
                headers=headers,
                params=params,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status != 200:
                    logger.warning("Pexels photos HTTP %d pour %r", resp.status, query)
                    return []
                data = await resp.json()

        for photo in data.get("photos", []):
            url = photo.get("src", {}).get("large2x") or photo.get("src", {}).get("large")
            if not url:
                continue

            photographer = photo.get("photographer", "Pexels")
            photographer_url = photo.get("photographer_url", "https://pexels.com")

            results.append({
                "source": "pexels",
                "url": url,
                "license": "Pexels License (libre d'utilisation)",
                "attribution": f"Photo par {photographer} via Pexels ({photographer_url})",
                "title": photo.get("alt") or query,
                "asset_type": "image",
            })
    except Exception as exc:
        logger.warning("Pexels photos search error: %s", exc)

    return results


async def _search_videos(query: str) -> list[dict]:
    headers = {"Authorization": settings.pexels_api_key}
    params = {
        "query": query,
        "per_page": "10",
        "orientation": "landscape",
    }

    results: list[dict] = []
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                VIDEOS_API_URL,
                headers=headers,
                params=params,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status != 200:
                    logger.warning("Pexels videos HTTP %d pour %r", resp.status, query)
                    return []
                data = await resp.json()

        for video in data.get("videos", []):
            video_url, width = _pick_pexels_video_file(video.get("video_files", []))
            if not video_url:
                continue

            user = video.get("user", {})
            author = user.get("name", "Pexels")
            author_url = user.get("url", "https://pexels.com")

            results.append({
                "source": "pexels",
                "url": video_url,
                "thumbnail_url": video.get("image"),
                "license": "Pexels License (libre d'utilisation)",
                "attribution": f"Vidéo par {author} via Pexels ({author_url})",
                "title": video.get("url", query).split("/")[-2] if video.get("url") else query,
                "asset_type": "video",
                "width": width,
                "duration_s": video.get("duration"),
            })
    except Exception as exc:
        logger.warning("Pexels videos search error: %s", exc)

    return results


def _pick_pexels_video_file(video_files: list[dict]) -> tuple[str | None, int | None]:
    """Choisit le fichier HD le plus large disponible."""
    candidates: list[tuple[int, str]] = []
    for item in video_files:
        link = item.get("link")
        if not link:
            continue
        width = int(item.get("width") or 0)
        quality = str(item.get("quality", "")).lower()
        if width >= 1280 or quality == "hd":
            candidates.append((width, link))

    if not candidates and video_files:
        item = max(video_files, key=lambda f: int(f.get("width") or 0))
        link = item.get("link")
        if link:
            return link, int(item.get("width") or 0) or None
        return None, None

    if not candidates:
        return None, None

    best_width, best_link = max(candidates, key=lambda pair: pair[0])
    return best_link, best_width or None
