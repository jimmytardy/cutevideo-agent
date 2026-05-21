from __future__ import annotations

import logging

import aiohttp

from agent.core.config import settings

logger = logging.getLogger(__name__)

API_URL = "https://api.unsplash.com/search/photos"


async def search(keywords: list[str], period: str = "") -> list[dict]:
    """Recherche sur Unsplash — photos libres de droits."""
    if not settings.unsplash_access_key:
        logger.debug("Unsplash access key non configurée, skip")
        return []

    query = " ".join(keywords[:3])
    headers = {"Authorization": f"Client-ID {settings.unsplash_access_key}"}
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
                    return []
                data = await resp.json()

        for photo in data.get("results", []):
            url = photo.get("urls", {}).get("regular") or photo.get("urls", {}).get("full")
            if not url:
                continue

            user = photo.get("user", {})
            name = user.get("name", "Unsplash")
            profile = user.get("links", {}).get("html", "https://unsplash.com")

            results.append({
                "source": "unsplash",
                "url": url,
                "license": "Unsplash License (libre d'utilisation)",
                "attribution": f"Photo par {name} sur Unsplash ({profile})",
                "title": photo.get("alt_description") or query,
            })
    except Exception as e:
        logger.warning("Unsplash search error: %s", e)

    return results
