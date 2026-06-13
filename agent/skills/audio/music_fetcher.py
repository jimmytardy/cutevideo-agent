from __future__ import annotations

import logging
from pathlib import Path

import aiohttp

from agent.core.config import settings

logger = logging.getLogger(__name__)

# Thème → requête de recherche pour la musique de fond
_THEME_QUERIES: dict[str, str] = {
    "histoire":    "documentary historical ambient background",
    "france":      "french classical ambient documentary",
    "nature":      "nature peaceful ambient background",
    "animaux":     "nature wildlife ambient peaceful",
    "science":     "science ambient electronic background",
    "art":         "classical piano ambient soft",
    "finance":     "corporate background music calm",
    "psychologie": "calm introspective ambient background",
    "true_crime":  "suspense dark ambient mystery",
    "tech":        "electronic technology ambient background",
    "default":     "background ambient documentary music",
}


async def fetch_background_music(
    theme_category: str = "default",
    output_dir: Path | None = None,
) -> Path | None:
    """
    Cherche et télécharge une piste de musique de fond adaptée au thème.
    Essaie Freesound en priorité, puis Pixabay Audio.
    Retourne le chemin local ou None si rien trouvé.
    """
    query = _THEME_QUERIES.get(theme_category.lower(), _THEME_QUERIES["default"])
    output_dir = output_dir or Path("./tmp/music")
    output_dir.mkdir(parents=True, exist_ok=True)

    path = await _fetch_freesound(query, output_dir)
    if path:
        return path

    return await _fetch_pixabay(query, output_dir)


async def _fetch_freesound(query: str, output_dir: Path) -> Path | None:
    api_key = getattr(settings, "freesound_api_key", None)
    if not api_key:
        logger.debug("Freesound API key non configurée, skip")
        return None

    params = {
        "query": query,
        "token": api_key,
        "filter": "duration:[30 TO 300] type:mp3",
        "fields": "id,name,previews,duration,license",
        "page_size": 5,
        "sort": "rating_desc",
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://freesound.org/apiv2/search/text/",
                params=params,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status != 200:
                    logger.warning("Freesound search HTTP %s", resp.status)
                    return None
                data = await resp.json()

            for item in data.get("results", []):
                preview_url = (
                    item.get("previews", {}).get("preview-hq-mp3")
                    or item.get("previews", {}).get("preview-lq-mp3")
                )
                if not preview_url:
                    continue

                dest = output_dir / f"music_freesound_{item['id']}.mp3"
                if dest.exists():
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

    except Exception as e:
        logger.warning("Freesound fetch error: %s", e)

    return None


async def _fetch_pixabay(query: str, output_dir: Path) -> Path | None:
    # Pixabay expose /api/music/ avec la même clé que les images/vidéos.
    # Endpoint non officiellement documenté — peut nécessiter approbation de compte.
    api_key = getattr(settings, "pixabay_api_key", None)
    if not api_key:
        logger.debug("Pixabay API key non configurée, skip")
        return None

    params = {"key": api_key, "q": query, "per_page": 5}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://pixabay.com/api/music/",
                params=params,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status != 200:
                    logger.warning("Pixabay music HTTP %s (endpoint peut être indisponible)", resp.status)
                    return None
                data = await resp.json()

            for item in data.get("hits", []):
                audio_url = item.get("audio")
                if not audio_url:
                    continue

                dest = output_dir / f"music_pixabay_{item['id']}.mp3"
                if dest.exists():
                    logger.debug("Pixabay music cache: %s", dest.name)
                    return dest

                async with session.get(
                    audio_url, timeout=aiohttp.ClientTimeout(total=60)
                ) as dl:
                    if dl.status != 200:
                        continue
                    dest.write_bytes(await dl.read())
                    logger.info("Pixabay music téléchargée : '%s' → %s", item.get("title", query), dest)
                    return dest

    except Exception as e:
        logger.warning("Pixabay music fetch error: %s", e)

    return None
