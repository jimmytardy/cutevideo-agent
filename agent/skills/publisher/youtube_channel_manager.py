from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from agent.skills.publisher import youtube_branding

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from agent.core.database import Channel

logger = logging.getLogger(__name__)


async def _fetch_stock_banner(keywords: list[str], tmpdir: str) -> Path | None:
    """Tente de télécharger une image panoramique depuis Pexels, Pixabay ou Unsplash."""
    import aiohttp

    from agent.skills.media_sources import pexels, pixabay, unsplash

    for source in (pexels, pixabay, unsplash):
        try:
            results = await source.search(keywords)
        except Exception:
            continue
        if not results:
            continue

        url = results[0].get("url")
        if not url:
            continue

        dest = Path(tmpdir) / "banner.jpg"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    if resp.status == 200:
                        dest.write_bytes(await resp.read())
                        logger.info("Bannière stock téléchargée depuis %s", source.__name__)
                        return dest
        except Exception as e:
            logger.debug("Échec téléchargement bannière depuis %s : %s", source.__name__, e)

    return None


async def generate_and_upload_banner(channel: Channel) -> bool:
    """Bannière YouTube : stock libre en priorité, AI en fallback."""
    from agent.core.config import settings

    if not channel.youtube_channel_id:
        return False

    theme = channel.theme_category or "nature"
    keywords = [theme, channel.name, "landscape", "background"]

    with tempfile.TemporaryDirectory() as tmpdir:
        # 1. Essayer les sources libres de droits
        banner_path = await _fetch_stock_banner(keywords, tmpdir)

        # 2. Fallback IA
        if not banner_path:
            from agent.skills.media_sources.ai.base import ImageGenerationRequest
            from agent.skills.media_sources.ai.registry import generate_with_plan

            brand_kit = channel.brand_kit or {}
            visual_style = brand_kit.get("visual_style", "modern and professional")
            prompt = (
                f"YouTube channel banner for a '{theme}' channel named '{channel.name}'. "
                f"Style: {visual_style}. "
                "Ultra-wide cinematic landscape, no text, no logos, pure atmospheric background."
            )
            request = ImageGenerationRequest(
                prompt=prompt,
                output_dir=Path(tmpdir),
                theme_category=theme,
                aspect_ratio="16:9",
                image_width=2560,
                image_height=1440,
            )
            result = await generate_with_plan("flux_pro", request) or await generate_with_plan("flux_schnell", request)
            if not result:
                logger.warning("Bannière introuvable (stock + AI) pour la chaîne %s", channel.slug)
                return False
            banner_path = result.local_path

        token = channel.youtube_refresh_token or settings.youtube_refresh_token or None
        try:
            await youtube_branding.upload_channel_banner(banner_path, channel.youtube_channel_id, token)
            logger.info("Bannière uploadée pour la chaîne %s", channel.slug)
            return True
        except Exception as e:
            logger.warning("Échec upload bannière pour %s : %s", channel.slug, e)
            return False


async def ensure_playlist_for_theme(
    channel: Channel,
    theme: str,
    db: AsyncSession,
) -> str | None:
    """Retourne l'ID de la playlist pour ce thème, la crée en DB et sur YouTube si absente."""
    from agent.core.config import settings

    if not channel.youtube_channel_id:
        return None

    config = dict(channel.config or {})
    playlists: dict[str, str] = config.get("yt_playlists", {})
    theme_key = theme[:50].lower().replace(" ", "_")

    if theme_key in playlists:
        return playlists[theme_key]

    token = channel.youtube_refresh_token or settings.youtube_refresh_token or None
    try:
        playlist_id = await youtube_branding.create_playlist(
            title=theme[:100],
            description=f"Vidéos sur le thème : {theme}",
            refresh_token=token,
        )
        playlists[theme_key] = playlist_id
        config["yt_playlists"] = playlists
        channel.config = config
        await db.commit()
        logger.info("Playlist créée '%s' → %s (chaîne %s)", theme, playlist_id, channel.slug)
        return playlist_id
    except Exception as e:
        logger.warning("Échec création playlist '%s' : %s", theme, e)
        return None


async def post_publish_hook(
    channel: Channel,
    yt_video_id: str,
    theme: str,
    db: AsyncSession,
) -> None:
    """Après publication YouTube : ajoute la vidéo à la playlist du thème et définit le trailer."""
    from agent.core.config import settings

    token = channel.youtube_refresh_token or settings.youtube_refresh_token or None

    # 1. Ajouter à la playlist du thème
    playlist_id = await ensure_playlist_for_theme(channel, theme, db)
    if playlist_id:
        try:
            await youtube_branding.add_video_to_playlist(playlist_id, yt_video_id, token)
            logger.info("Vidéo %s ajoutée à la playlist %s", yt_video_id, playlist_id)
        except Exception as e:
            logger.warning("Échec ajout playlist : %s", e)

    # 2. Définir comme trailer si c'est la première vidéo publiée sur cette chaîne
    config = dict(channel.config or {})
    if not config.get("yt_trailer_video_id") and channel.youtube_channel_id:
        try:
            await youtube_branding.set_channel_trailer(
                channel.youtube_channel_id, yt_video_id, token
            )
            config["yt_trailer_video_id"] = yt_video_id
            channel.config = config
            await db.commit()
            logger.info("Trailer défini : %s pour la chaîne %s", yt_video_id, channel.slug)
        except Exception as e:
            logger.warning("Échec définition trailer : %s", e)
