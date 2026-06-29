from __future__ import annotations

import logging
from pathlib import Path

import aiohttp

from agent.core.config import settings

logger = logging.getLogger(__name__)

IA_SEARCH_URL = "https://archive.org/advancedsearch.php"
IA_METADATA_URL = "https://archive.org/metadata/{identifier}"
IA_DOWNLOAD_URL = "https://archive.org/download/{identifier}/{filename}"
AUDIO_EXTENSIONS = (".mp3", ".ogg", ".wav", ".flac", ".m4a")

# Thème de chaîne → requête de recherche musicale
_THEME_QUERIES: dict[str, str] = {
    "histoire":    "documentary ambient cinematic",
    "france":      "ambient documentary calm",
    "nature":      "nature peaceful ambient",
    "animaux":     "nature wildlife ambient",
    "science":     "science ambient electronic",
    "art":         "classical piano ambient",
    "finance":     "corporate background calm",
    "psychologie": "calm introspective ambient",
    "true_crime":  "suspense dark ambient mystery",
    "tech":        "electronic technology ambient",
    "default":     "ambient background music",
}

# Mood YouTube/TikTok → requête de recherche musicale
_MOOD_QUERIES: dict[str, str] = {
    "energique":    "upbeat energetic uplifting",
    "calme":        "calm relaxing ambient peaceful",
    "dramatique":   "dramatic cinematic orchestral",
    "mysterieux":   "mysterious suspense ambient dark",
    "inspirant":    "inspirational uplifting motivational",
    "humoristique": "fun quirky upbeat playful",
    "tension":      "tension suspense thriller",
    "revelateur":   "epic reveal cinematic",
}


async def fetch_background_music(
    theme_category: str = "default",
    output_dir: Path | None = None,
) -> Path | None:
    """Cherche et télécharge une piste de musique de fond adaptée au thème de chaîne."""
    query = _THEME_QUERIES.get(theme_category.lower(), _THEME_QUERIES["default"])
    output_dir = output_dir or Path("./tmp/music")
    output_dir.mkdir(parents=True, exist_ok=True)

    for fetcher in (_fetch_freesound, _fetch_internet_archive):
        path = await fetcher(query, output_dir)
        if path:
            return path
    return None


async def fetch_music_for_mood(
    mood: str,
    output_dir: Path | None = None,
) -> Path | None:
    """Cherche et télécharge une piste musicale adaptée au mood YouTube/TikTok."""
    query = _MOOD_QUERIES.get(mood.lower(), _MOOD_QUERIES["calme"])
    output_dir = output_dir or Path("./tmp/music")
    output_dir.mkdir(parents=True, exist_ok=True)

    for fetcher in (_fetch_freesound, _fetch_internet_archive):
        path = await fetcher(query, output_dir)
        if path:
            return path
    return None


async def _fetch_freesound(query: str, output_dir: Path) -> Path | None:
    from agent.skills.media.rights_check import is_publishable

    api_key = settings.freesound_api_key
    if not api_key:
        logger.debug("Freesound API key non configurée, skip")
        return None

    params = {
        "query": query,
        "filter": "duration:[30 TO 300]",
        "fields": "id,name,previews,duration,license",
        "page_size": 5,
        "sort": "rating_desc",
    }
    headers = {"Authorization": f"Token {api_key}"}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://freesound.org/apiv2/search/text/",
                params=params,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status != 200:
                    logger.warning("Freesound search HTTP %s", resp.status)
                    return None
                data = await resp.json()

            for item in data.get("results", []):
                license_raw = str(item.get("license") or "")
                ok, reason = is_publishable({"license": license_raw, "source": "freesound"})
                if not ok:
                    logger.debug("Freesound piste ignorée (licence) : %s", reason)
                    continue

                preview_url = (
                    item.get("previews", {}).get("preview-hq-mp3")
                    or item.get("previews", {}).get("preview-lq-mp3")
                )
                if not preview_url:
                    continue

                dest = output_dir / f"music_freesound_{item['id']}.mp3"
                if dest.exists() and dest.stat().st_size > 0:
                    logger.debug("Freesound cache: %s", dest.name)
                    return dest

                async with session.get(
                    preview_url, timeout=aiohttp.ClientTimeout(total=60)
                ) as dl:
                    if dl.status != 200:
                        continue
                    dest.write_bytes(await dl.read())
                    logger.info("Freesound music téléchargée : '%s' → %s", item["name"], dest)
                    return dest

    except Exception as exc:
        logger.warning("Freesound fetch error: %s", exc)

    return None


async def _fetch_internet_archive(query: str, output_dir: Path) -> Path | None:
    """Télécharge une piste audio domaine public depuis Internet Archive."""
    from agent.skills.media_sources.internet_archive import _is_open_license

    safe_query = " ".join(query.split()[:4])
    params = {
        "q": f"({safe_query}) AND mediatype:audio",
        "fl[]": ["identifier", "title", "licenseurl"],
        "rows": "8",
        "page": "1",
        "output": "json",
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                IA_SEARCH_URL, params=params, timeout=aiohttp.ClientTimeout(total=20)
            ) as resp:
                if resp.status != 200:
                    logger.warning("Internet Archive music search HTTP %s", resp.status)
                    return None
                data = await resp.json()

            for doc in data.get("response", {}).get("docs", []):
                identifier = doc.get("identifier", "")
                license_url = str(doc.get("licenseurl") or "")
                if not identifier or not license_url or not _is_open_license(license_url):
                    continue

                dest = await _download_ia_audio(session, identifier, output_dir)
                if dest:
                    title = doc.get("title", identifier)
                    logger.info("Internet Archive music téléchargée : '%s' → %s", title, dest)
                    return dest

    except Exception as exc:
        logger.warning("Internet Archive music fetch error: %s", exc)

    return None


async def _download_ia_audio(
    session: aiohttp.ClientSession,
    identifier: str,
    output_dir: Path,
) -> Path | None:
    metadata_url = IA_METADATA_URL.format(identifier=identifier)
    async with session.get(metadata_url, timeout=aiohttp.ClientTimeout(total=20)) as resp:
        if resp.status != 200:
            return None
        meta = await resp.json()

    for file_info in meta.get("files", []):
        filename = file_info.get("name", "")
        if not filename.lower().endswith(AUDIO_EXTENSIONS):
            continue
        if file_info.get("format", "").lower() in {"metadata", "json"}:
            continue

        dest = output_dir / f"music_ia_{identifier}_{filename}"
        if dest.exists() and dest.stat().st_size > 0:
            return dest

        download_url = IA_DOWNLOAD_URL.format(identifier=identifier, filename=filename)
        async with session.get(download_url, timeout=aiohttp.ClientTimeout(total=120)) as dl:
            if dl.status != 200:
                continue
            content = await dl.read()
            if len(content) < 50_000:
                continue
            dest.write_bytes(content)
            return dest

    return None
