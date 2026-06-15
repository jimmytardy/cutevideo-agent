from __future__ import annotations

import logging
from typing import Literal

import aiohttp

from agent.core.config import settings

logger = logging.getLogger(__name__)

API_URL = "https://api.europeana.eu/record/v2/search.json"
MediaType = Literal["image", "video"]


async def search(
    keywords: list[str],
    period: str = "",
    *,
    media_type: MediaType = "image",
) -> list[dict]:
    """Recherche sur Europeana — patrimoine culturel européen (images ou vidéos)."""
    if not settings.europeana_api_key:
        logger.debug("Europeana API key non configurée, skip")
        return []

    query = " ".join(keywords[:3])
    asset_filter = "TYPE:VIDEO" if media_type == "video" else "TYPE:IMAGE"
    params = {
        "wskey": settings.europeana_api_key,
        "query": query,
        "qf": [asset_filter, "RIGHTS:*open*"],
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
            preview = (item.get("edmPreview") or [None])[0]

            entry: dict = {
                "source": "europeana",
                "url": url,
                "license": rights,
                "attribution": (
                    f"{provider} via Europeana — {creator}"
                    if creator
                    else f"{provider} via Europeana"
                ),
                "title": title,
                "asset_type": "video" if media_type == "video" else "image",
            }
            if media_type == "video" and preview:
                entry["thumbnail_url"] = preview
            results.append(entry)
    except Exception as exc:
        logger.warning("Europeana search error: %s", exc)

    return results


def _is_open_rights(rights_url: str) -> bool:
    open_keywords = ["creativecommons", "publicdomain", "cc0", "cc-by"]
    return any(kw in rights_url.lower() for kw in open_keywords)
