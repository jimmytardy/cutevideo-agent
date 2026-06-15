from __future__ import annotations

import logging
from typing import Literal

import aiohttp

logger = logging.getLogger(__name__)

API_URL = "https://commons.wikimedia.org/w/api.php"
MIN_WIDTH = 1280
MediaType = Literal["image", "video"]


async def search(
    keywords: list[str],
    period: str = "",
    *,
    media_type: MediaType = "image",
) -> list[dict]:
    """Recherche des images ou vidéos libres sur Wikimedia Commons."""
    query = " ".join(keywords[:3])
    file_filter = "filetype:video" if media_type == "video" else "filetype:bitmap"
    params = {
        "action": "query",
        "format": "json",
        "generator": "search",
        "gsrsearch": f"{file_filter} {query}",
        "gsrlimit": "10",
        "prop": "imageinfo",
        "iiprop": "url|size|extmetadata|mime",
        "iiurlwidth": str(MIN_WIDTH),
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

        pages = data.get("query", {}).get("pages", {})
        for page in pages.values():
            info = page.get("imageinfo", [{}])[0]
            mime = info.get("mime", "")
            if media_type == "video" and not mime.startswith("video/"):
                continue

            url = info.get("url", "") if media_type == "video" else (
                info.get("thumburl") or info.get("url", "")
            )
            if not url:
                continue

            meta = info.get("extmetadata", {})
            license_short = meta.get("LicenseShortName", {}).get("value", "")
            artist = meta.get("Artist", {}).get("value", "")

            if not _is_free_license(license_short):
                continue

            item: dict = {
                "source": "wikimedia",
                "url": url,
                "license": license_short,
                "attribution": f"Wikimedia Commons — {artist}" if artist else "Wikimedia Commons",
                "title": page.get("title", ""),
                "asset_type": "video" if media_type == "video" else "image",
            }
            if media_type == "image":
                item["width"] = info.get("thumbwidth") or info.get("width")
            else:
                item["width"] = info.get("width")
            results.append(item)
    except Exception as exc:
        logger.warning("Wikimedia search error: %s", exc)

    return results


def _is_free_license(license_str: str) -> bool:
    free_keywords = ["CC0", "CC BY", "CC-BY", "Public Domain", "PDM", "CC BY-SA"]
    return any(kw.lower() in license_str.lower() for kw in free_keywords)
