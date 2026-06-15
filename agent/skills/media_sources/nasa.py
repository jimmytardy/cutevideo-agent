from __future__ import annotations

import logging
import re
from typing import Literal

import aiohttp

logger = logging.getLogger(__name__)

SEARCH_API_URL = "https://images-api.nasa.gov/search"
MediaType = Literal["image", "video"]
VIDEO_EXTENSIONS = (".mp4", ".mov", ".webm")
YEAR_RE = re.compile(r"\b(1[0-9]{3}|20[0-9]{2})\b")


async def search(
    keywords: list[str],
    period: str = "",
    *,
    media_type: MediaType = "image",
) -> list[dict]:
    """Recherche sur la NASA Image and Video Library (domaine public US)."""
    query = " ".join(keywords[:4])
    if not query.strip():
        return []

    if media_type == "video":
        return await _search_videos(query, period)
    return await _search_images(query, period)


async def _search_images(query: str, period: str) -> list[dict]:
    params: dict[str, str | int] = {
        "q": query,
        "media_type": "image",
        "page_size": 10,
    }
    year = _extract_year(period)
    if year:
        params["year_start"] = year
        params["year_end"] = year

    results: list[dict] = []
    try:
        async with aiohttp.ClientSession() as session:
            items = await _fetch_search_items(session, params)
            for item in items:
                meta = (item.get("data") or [{}])[0]
                url = pick_nasa_image_url(item.get("links") or [])
                if not url:
                    continue
                title = meta.get("title") or meta.get("nasa_id") or query
                center = meta.get("center", "NASA")
                results.append({
                    "source": "nasa",
                    "url": url,
                    "license": "NASA Media (domaine public US)",
                    "attribution": f"NASA / {center} — {title}",
                    "title": title,
                    "asset_type": "image",
                    "width": _link_width(item.get("links") or [], url),
                })
    except Exception as exc:
        logger.warning("NASA image search error: %s", exc)

    return results


async def _search_videos(query: str, period: str) -> list[dict]:
    params: dict[str, str | int] = {
        "q": query,
        "media_type": "video",
        "page_size": 6,
    }
    year = _extract_year(period)
    if year:
        params["year_start"] = year
        params["year_end"] = year

    results: list[dict] = []
    try:
        async with aiohttp.ClientSession() as session:
            items = await _fetch_search_items(session, params)
            for item in items:
                meta = (item.get("data") or [{}])[0]
                manifest_href = item.get("href")
                if not manifest_href:
                    continue

                manifest = await _fetch_manifest(session, manifest_href)
                if not manifest:
                    continue

                video_url = pick_nasa_video_url(manifest)
                if not video_url:
                    continue

                title = meta.get("title") or meta.get("nasa_id") or query
                center = meta.get("center", "NASA")
                thumbnail = pick_nasa_thumbnail(manifest, item.get("links") or [])

                results.append({
                    "source": "nasa",
                    "url": video_url,
                    "thumbnail_url": thumbnail,
                    "license": "NASA Media (domaine public US)",
                    "attribution": f"NASA / {center} — {title}",
                    "title": title,
                    "asset_type": "video",
                })
    except Exception as exc:
        logger.warning("NASA video search error: %s", exc)

    return results


async def _fetch_search_items(
    session: aiohttp.ClientSession,
    params: dict[str, str | int],
) -> list[dict]:
    async with session.get(
        SEARCH_API_URL,
        params=params,
        timeout=aiohttp.ClientTimeout(total=20),
    ) as resp:
        if resp.status != 200:
            logger.warning("NASA search HTTP %d pour %r", resp.status, params.get("q"))
            return []
        data = await resp.json()
    return list(data.get("collection", {}).get("items", []))


async def _fetch_manifest(
    session: aiohttp.ClientSession,
    manifest_href: str,
) -> list[str]:
    async with session.get(
        manifest_href,
        timeout=aiohttp.ClientTimeout(total=20),
    ) as resp:
        if resp.status != 200:
            return []
        payload = await resp.json()
    if isinstance(payload, list):
        return [str(entry) for entry in payload]
    return []


def pick_nasa_image_url(links: list[dict]) -> str | None:
    """Choisit la meilleure image NASA (~orig > ~large > ~medium)."""
    hrefs = [str(link.get("href", "")) for link in links if link.get("render") == "image"]
    if not hrefs:
        hrefs = [str(link.get("href", "")) for link in links if link.get("href")]

    for suffix in ("~orig.jpg", "~orig.png", "~large.jpg", "~medium.jpg", "~small.jpg"):
        for href in hrefs:
            if href.lower().endswith(suffix):
                return href.replace("http://", "https://")
    return None


def pick_nasa_video_url(manifest: list[str]) -> str | None:
    """Choisit un MP4 équilibré qualité/poids pour le pipeline."""
    mp4_urls = [
        url.replace("http://", "https://")
        for url in manifest
        if url.lower().endswith(VIDEO_EXTENSIONS) and "metadata.json" not in url.lower()
    ]
    if not mp4_urls:
        return None

    def _score(url: str) -> tuple[int, int]:
        lower = url.lower()
        if "~medium.mp4" in lower and not re.search(r"~medium_\d+\.mp4", lower):
            return (4, 0)
        if "~preview.mp4" in lower:
            return (3, 0)
        if "~small.mp4" in lower and not re.search(r"~small_\d+\.mp4", lower):
            return (2, 0)
        if "~mobile.mp4" in lower:
            return (1, 0)
        if "~orig.mp4" in lower:
            return (0, 0)
        return (0, 1)

    return max(mp4_urls, key=_score)


def pick_nasa_thumbnail(manifest: list[str], links: list[dict]) -> str | None:
    for suffix in ("~large.jpg", "~medium.jpg", "~thumb.jpg"):
        for url in manifest:
            if url.lower().endswith(suffix):
                return url.replace("http://", "https://")

    for link in links:
        href = str(link.get("href", ""))
        if link.get("render") == "image" and href:
            return href.replace("http://", "https://")
    return None


def _link_width(links: list[dict], selected_url: str) -> int | None:
    for link in links:
        href = str(link.get("href", "")).replace("http://", "https://")
        if href == selected_url and link.get("width"):
            return int(link["width"])
    return None


def _extract_year(period: str) -> str | None:
    if not period:
        return None
    match = YEAR_RE.search(period)
    return match.group(1) if match else None
