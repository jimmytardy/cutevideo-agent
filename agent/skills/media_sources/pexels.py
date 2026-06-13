from __future__ import annotations

import logging

import aiohttp

from agent.core.config import settings

logger = logging.getLogger(__name__)

API_URL = "https://api.pexels.com/v1/search"


async def search(keywords: list[str], period: str = "") -> list[dict]:
    """Recherche sur Pexels — photos et vidéos libres."""
    if not settings.pexels_api_key:
        logger.debug("Pexels API key non configurée, skip")
        return []

    query = " ".join(keywords[:3])
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
                API_URL, headers=headers, params=params,
                timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                if resp.status != 200:
                    logger.warning("Pexels HTTP %d pour la requête %r", resp.status, query)
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
            })
    except Exception as e:
        logger.warning("Pexels search error: %s", e)

    return results
