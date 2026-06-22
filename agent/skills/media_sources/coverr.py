from __future__ import annotations

import logging
from typing import Literal

import aiohttp

from agent.core.config import settings

logger = logging.getLogger(__name__)

API_URL = "https://api.coverr.co/videos"
MediaType = Literal["image", "video"]
VideoOrientation = Literal["landscape", "portrait"]

_LICENSE = "Coverr License (libre usage commercial)"
_ATTRIBUTION = "Vidéo via Coverr (https://coverr.co)"


async def search(
    keywords: list[str],
    period: str = "",
    *,
    media_type: MediaType = "image",
    orientation: VideoOrientation = "landscape",
) -> list[dict]:
    """Recherche vidéos stock Coverr — vidéos uniquement (pas d'images)."""
    if media_type != "video":
        return []
    if not settings.coverr_api_key:
        logger.debug("Coverr API key non configurée, skip")
        return []

    query = " ".join(keywords[:3])
    return await _search_videos(query, orientation=orientation)


async def _search_videos(
    query: str,
    *,
    orientation: VideoOrientation = "landscape",
) -> list[dict]:
    headers = {"Authorization": f"Bearer {settings.coverr_api_key}"}
    params: dict[str, str | int | bool] = {
        "page_size": 10,
        "urls": "true",
        "sort": "popular",
    }
    if query.strip():
        params["query"] = query.strip()

    results: list[dict] = []
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                API_URL,
                headers=headers,
                params=params,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status != 200:
                    logger.warning("Coverr videos HTTP %d pour %r", resp.status, query)
                    return []
                data = await resp.json()

        want_vertical = orientation == "portrait"
        for hit in data.get("hits", []):
            is_vertical = bool(hit.get("is_vertical"))
            if want_vertical and not is_vertical:
                continue
            if not want_vertical and is_vertical:
                continue

            urls = hit.get("urls") or {}
            video_url = urls.get("mp4_download") or urls.get("mp4") or ""
            if not video_url:
                continue

            width = hit.get("max_width")
            duration = hit.get("duration")
            video_id = hit.get("id", "")

            results.append({
                "source": "coverr",
                "url": video_url,
                "coverr_video_id": video_id,
                "thumbnail_url": hit.get("thumbnail") or hit.get("poster"),
                "license": _LICENSE,
                "attribution": _ATTRIBUTION,
                "title": hit.get("title") or query or "Coverr video",
                "asset_type": "video",
                "width": int(width) if width else None,
                "duration_s": float(duration) if duration is not None else None,
            })
    except Exception as exc:
        logger.warning("Coverr videos search error: %s", exc)

    return results


async def record_download(video_id: str) -> None:
    """Enregistre un téléchargement Coverr (stats API — recommandé par Coverr)."""
    if not settings.coverr_api_key or not video_id:
        return
    headers = {"Authorization": f"Bearer {settings.coverr_api_key}"}
    url = f"{API_URL}/{video_id}/stats/downloads"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.patch(
                url,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status not in (200, 204):
                    logger.debug("Coverr download stat HTTP %d pour %s", resp.status, video_id)
    except Exception as exc:
        logger.debug("Coverr download stat échoué %s : %s", video_id, exc)
