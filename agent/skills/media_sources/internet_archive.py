from __future__ import annotations

import logging
from typing import Literal

import aiohttp

logger = logging.getLogger(__name__)

API_URL = "https://archive.org/advancedsearch.php"
METADATA_URL = "https://archive.org/metadata/{identifier}"
DOWNLOAD_URL = "https://archive.org/download/{identifier}/{filename}"
MediaType = Literal["image", "video"]
VIDEO_EXTENSIONS = (".mp4", ".ogv", ".webm", ".mpeg", ".mov")


async def search(
    keywords: list[str],
    period: str = "",
    *,
    media_type: MediaType = "image",
) -> list[dict]:
    """Recherche sur Internet Archive — images ou films domaine public."""
    if media_type == "video":
        return await _search_videos(keywords)
    return await _search_images(keywords)


async def _search_images(keywords: list[str]) -> list[dict]:
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

            image_url = f"https://archive.org/services/img/{identifier}"

            results.append({
                "source": "internet_archive",
                "url": image_url,
                "license": license_url or "domaine public",
                "attribution": f"Internet Archive — {creator or title}",
                "title": title,
                "asset_type": "image",
            })
    except Exception as exc:
        logger.warning("Internet Archive image search error: %s", exc)

    return results


async def _search_videos(keywords: list[str]) -> list[dict]:
    query = " AND ".join(f'"{kw}"' for kw in keywords[:2] if kw)
    if not query:
        return []

    params = {
        "q": f"({query}) AND (mediatype:movies OR mediatype:video)",
        "fl[]": ["identifier", "title", "creator", "licenseurl"],
        "rows": "8",
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

                if not identifier or not _is_open_license(license_url):
                    continue

                resolved = await _resolve_video_file(session, identifier)
                if not resolved:
                    continue

                video_url, width = resolved
                results.append({
                    "source": "internet_archive",
                    "url": video_url,
                    "thumbnail_url": f"https://archive.org/services/img/{identifier}",
                    "license": license_url or "domaine public",
                    "attribution": f"Internet Archive — {creator or title}",
                    "title": title,
                    "asset_type": "video",
                    "width": width,
                })
    except Exception as exc:
        logger.warning("Internet Archive video search error: %s", exc)

    return results


async def _resolve_video_file(
    session: aiohttp.ClientSession,
    identifier: str,
) -> tuple[str, int | None] | None:
    meta_url = METADATA_URL.format(identifier=identifier)
    try:
        async with session.get(meta_url, timeout=aiohttp.ClientTimeout(total=20)) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()
    except Exception:
        return None

    picked = pick_best_video_file(data.get("files", []))
    if not picked:
        return None

    filename, width = picked
    return DOWNLOAD_URL.format(identifier=identifier, filename=filename), width


def pick_best_video_file(files: list[dict]) -> tuple[str, int | None] | None:
    """Sélectionne le meilleur fichier vidéo MP4/WebM dans les métadonnées IA."""
    candidates: list[tuple[int, int, str]] = []
    for item in files:
        name = str(item.get("name", ""))
        if item.get("private") == "true":
            continue
        if not name.lower().endswith(VIDEO_EXTENSIONS):
            continue
        if name.endswith(".torrent") or name.endswith(".xml"):
            continue

        width = int(item.get("width") or 0)
        size = int(item.get("size") or 0)
        fmt = str(item.get("format", "")).lower()
        score = width
        if name.lower().endswith(".mp4"):
            score += 500
        if "h.264" in fmt or "mpeg4" in fmt:
            score += 200
        candidates.append((score, size, name))

    if not candidates:
        return None

    _, _, best_name = max(candidates, key=lambda row: (row[0], row[1]))
    width = next(
        (int(item.get("width") or 0) or None for item in files if item.get("name") == best_name),
        None,
    )
    return best_name, width


def _is_open_license(license_url: str) -> bool:
    if not license_url:
        return True
    open_keywords = ["creativecommons", "publicdomain", "cc0", "cc-by"]
    return any(kw in license_url.lower() for kw in open_keywords)
