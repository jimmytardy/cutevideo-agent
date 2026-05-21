from __future__ import annotations

import logging
from urllib.parse import quote

import aiohttp

logger = logging.getLogger(__name__)

API_URL = "https://commons.wikimedia.org/w/api.php"
MIN_WIDTH = 1280


async def search(keywords: list[str], period: str = "") -> list[dict]:
    """Recherche des images libres sur Wikimedia Commons."""
    query = " ".join(keywords[:3])
    params = {
        "action": "query",
        "format": "json",
        "generator": "search",
        "gsrsearch": f"filetype:bitmap {query}",
        "gsrlimit": "10",
        "prop": "imageinfo",
        "iiprop": "url|size|extmetadata",
        "iiurlwidth": str(MIN_WIDTH),
    }

    results: list[dict] = []
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(API_URL, params=params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()

        pages = data.get("query", {}).get("pages", {})
        for page in pages.values():
            info = page.get("imageinfo", [{}])[0]
            url = info.get("thumburl") or info.get("url", "")
            if not url:
                continue

            meta = info.get("extmetadata", {})
            license_short = meta.get("LicenseShortName", {}).get("value", "")
            artist = meta.get("Artist", {}).get("value", "")

            if not _is_free_license(license_short):
                continue

            results.append({
                "source": "wikimedia",
                "url": url,
                "license": license_short,
                "attribution": f"Wikimedia Commons — {artist}" if artist else "Wikimedia Commons",
                "title": page.get("title", ""),
            })
    except Exception as e:
        logger.warning("Wikimedia search error: %s", e)

    return results


def _is_free_license(license_str: str) -> bool:
    free_keywords = ["CC0", "CC BY", "CC-BY", "Public Domain", "PDM", "CC BY-SA"]
    return any(kw.lower() in license_str.lower() for kw in free_keywords)
