from __future__ import annotations

import logging

import aiohttp

from agent.core.config import settings

logger = logging.getLogger(__name__)

API_URL = "https://pixabay.com/api/"


async def search(keywords: list[str], period: str = "") -> list[dict]:
    """Recherche sur Pixabay — photos libres de droits."""
    if not settings.pixabay_api_key:
        logger.debug("Pixabay API key non configurée, skip")
        return []

    query = " ".join(keywords[:3])
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
                    logger.warning("Pixabay HTTP %d pour la requête %r", resp.status, query)
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
            })
    except Exception as e:
        logger.warning("Pixabay search error: %s", e)

    return results
