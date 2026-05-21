from __future__ import annotations

import logging

import aiohttp

from agent.core.config import settings

logger = logging.getLogger(__name__)

API_URL = "https://api.europeana.eu/record/v2/search.json"


async def search(keywords: list[str], period: str = "") -> list[dict]:
    """Recherche sur Europeana — patrimoine culturel européen."""
    if not settings.europeana_api_key:
        logger.debug("Europeana API key non configurée, skip")
        return []

    query = " ".join(keywords[:3])
    params = {
        "wskey": settings.europeana_api_key,
        "query": query,
        "qf": ["TYPE:IMAGE", "RIGHTS:*open*"],
        "rows": "10",
        "profile": "rich",
    }

    results: list[dict] = []
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                API_URL, params=params, timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()

        for item in data.get("items", []):
            url = (item.get("edmIsShownBy") or [None])[0]
            if not url:
                url = (item.get("edmPreview") or [None])[0]
            if not url:
                continue

            rights = (item.get("rights") or [""])[0]
            if not _is_open_rights(rights):
                continue

            title = (item.get("title") or ["Europeana"])[0]
            creator = (item.get("dcCreator") or [""])[0]
            provider = (item.get("dataProvider") or ["Europeana"])[0]

            results.append({
                "source": "europeana",
                "url": url,
                "license": rights,
                "attribution": f"{provider} via Europeana — {creator}" if creator else f"{provider} via Europeana",
                "title": title,
            })
    except Exception as e:
        logger.warning("Europeana search error: %s", e)

    return results


def _is_open_rights(rights_url: str) -> bool:
    open_keywords = ["creativecommons", "publicdomain", "cc0", "cc-by"]
    return any(kw in rights_url.lower() for kw in open_keywords)
