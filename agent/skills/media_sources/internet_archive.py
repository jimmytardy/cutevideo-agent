from __future__ import annotations

import logging

import aiohttp

logger = logging.getLogger(__name__)

API_URL = "https://archive.org/advancedsearch.php"
DOWNLOAD_URL = "https://archive.org/download/{identifier}/{filename}"


async def search(keywords: list[str], period: str = "") -> list[dict]:
    """Recherche sur Internet Archive — documents historiques et films anciens."""
    query = " AND ".join(f'"{kw}"' for kw in keywords[:2] if kw)
    params = {
        "q": f"({query}) AND mediatype:image",
        "fl[]": ["identifier", "title", "creator", "licenseurl"],
        "rows": "10",
        "page": "1",
        "output": "json",
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

        for doc in data.get("response", {}).get("docs", []):
            identifier = doc.get("identifier", "")
            title = doc.get("title", identifier)
            creator = doc.get("creator", "")
            license_url = doc.get("licenseurl", "")

            if not _is_open_license(license_url):
                continue

            image_url = f"https://archive.org/thumbnail/{identifier}"

            results.append({
                "source": "internet_archive",
                "url": image_url,
                "license": license_url or "domaine public",
                "attribution": f"Internet Archive — {creator or title}",
                "title": title,
            })
    except Exception as e:
        logger.warning("Internet Archive search error: %s", e)

    return results


def _is_open_license(license_url: str) -> bool:
    if not license_url:
        return True
    open_keywords = ["creativecommons", "publicdomain", "cc0", "cc-by"]
    return any(kw in license_url.lower() for kw in open_keywords)
