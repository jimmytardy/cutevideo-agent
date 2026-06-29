from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select

from agent.core.api_keys import fetch_api_key
from agent.core.base_agent import BaseAgent
from agent.core.config import load_agent_config, settings
from agent.core.database import Analytics, AsyncSessionFactory, Channel, Publication, Video
from agent.core.market_research_models import CompetitorProfile
from agent.skills.market_research.youtube_discovery import (
    YouTubeAuthError,
    discover_youtube_landscape,
    list_channel_top_videos,
)
from agent.skills.video.style_extractor import (
    download_reference_video,
    edit_grammar_to_montage_profile,
    extract_edit_grammar_from_paths,
    load_style_config,
)

logger = logging.getLogger(__name__)


class StyleDirectorAgent(BaseAgent):
    """Agent niveau chaîne — infère montage_profile depuis vidéos de référence."""

    name = "style_director_agent"

    async def run(self, input_data: uuid.UUID | None = None) -> dict[str, Any]:
        if input_data is None:
            return await self.run_scheduled()
        return await self.run_for_channel(input_data)

    async def run_scheduled(self) -> dict[str, int]:
        processed = 0
        skipped = 0
        errors = 0

        async with AsyncSessionFactory() as session:
            result = await session.execute(
                select(Channel).where(Channel.is_active == True)  # noqa: E712
            )
            channels = list(result.scalars().all())

        for channel in channels:
            try:
                outcome = await self.run_for_channel(channel.id, force=False)
                if outcome.get("skipped"):
                    skipped += 1
                elif outcome.get("updated"):
                    processed += 1
                else:
                    skipped += 1
            except Exception as exc:
                errors += 1
                logger.error("StyleDirector échoué pour %s : %s", channel.slug, exc)

        summary = {"processed": processed, "skipped": skipped, "errors": errors}
        logger.info("StyleDirector planifié : %s", summary)
        return summary

    async def run_for_channel(
        self,
        channel_id: uuid.UUID,
        *,
        force: bool = False,
    ) -> dict[str, Any]:
        async with AsyncSessionFactory() as session:
            channel = await session.get(Channel, channel_id)
            if not channel:
                raise ValueError(f"Chaîne {channel_id} introuvable")

            if not force and self._should_skip_refresh(channel):
                return {
                    "channel_id": str(channel_id),
                    "skipped": True,
                    "reason": "refresh_not_due",
                }

            refs = await self._collect_reference_urls(channel)
            if not refs:
                logger.info(
                    "StyleDirector — aucune référence pour %s, profil inchangé",
                    channel.slug,
                )
                return {
                    "channel_id": str(channel_id),
                    "skipped": True,
                    "reason": "no_references",
                    "updated": False,
                }

            api_key = await self._resolve_gemini_key(channel.user_id)
            if not api_key:
                raise RuntimeError("Clé Gemini manquante pour StyleDirector")

            paths = await self._resolve_local_paths(refs)
            if not paths:
                return {
                    "channel_id": str(channel_id),
                    "skipped": True,
                    "reason": "download_failed",
                    "updated": False,
                }

            short_grammar, long_grammar = await extract_edit_grammar_from_paths(
                paths,
                api_key=api_key,
            )
            if short_grammar is None and long_grammar is None:
                return {
                    "channel_id": str(channel_id),
                    "skipped": True,
                    "reason": "analysis_failed",
                    "updated": False,
                }

            profile = edit_grammar_to_montage_profile(
                short_grammar,
                long_grammar,
                reference_count=len(paths),
            )

            cfg = dict(channel.config or {})
            cfg["montage_profile"] = profile
            channel.config = cfg
            session.add(channel)
            await session.commit()

            logger.info(
                "StyleDirector — profil montage mis à jour pour %s (%d références)",
                channel.slug,
                len(paths),
            )
            return {
                "channel_id": str(channel_id),
                "updated": True,
                "reference_count": len(paths),
                "montage_profile": profile,
            }

    def _should_skip_refresh(self, channel: Channel) -> bool:
        style_cfg = load_style_config()
        refresh_days = int(style_cfg.get("refresh_days", 30))
        mp = (channel.config or {}).get("montage_profile") or {}
        meta = mp.get("meta") or {}
        updated_raw = meta.get("updated_at")
        if not updated_raw:
            return False
        try:
            updated_at = datetime.fromisoformat(str(updated_raw).replace("Z", "+00:00"))
        except ValueError:
            return False
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)
        cutoff = datetime.now(timezone.utc) - timedelta(days=refresh_days)
        return updated_at >= cutoff

    async def _resolve_gemini_key(self, user_id: uuid.UUID) -> str | None:
        try:
            ctx = await fetch_api_key(user_id, "gemini", purpose="video_analysis", tier="free")
            if ctx.key:
                return ctx.key
        except Exception as exc:
            logger.debug("fetch_api_key gemini : %s", exc)
        return (settings.google_gemini_api_key or "").strip() or None

    async def _collect_reference_urls(self, channel: Channel) -> list[str]:
        style_cfg = load_style_config()
        max_refs = int(style_cfg.get("max_reference_videos", 12))
        competitor_ratio = float(style_cfg.get("competitor_video_ratio", 0.6))
        max_competitor = max(1, int(max_refs * competitor_ratio))
        max_own = max(0, max_refs - max_competitor)

        token = channel.youtube_refresh_token or settings.youtube_refresh_token or None
        competitor_urls: list[str] = []
        own_urls: list[str] = []

        market = (channel.config or {}).get("market_research") or {}
        competitors_raw = market.get("top_competitors") or []
        for item in competitors_raw:
            if len(competitor_urls) >= max_competitor:
                break
            try:
                comp = CompetitorProfile.model_validate(item)
            except Exception:
                continue
            if not comp.handle_or_url:
                continue
            try:
                videos = await list_channel_top_videos(
                    comp.handle_or_url,
                    token,
                    max_videos=2,
                )
            except YouTubeAuthError:
                logger.warning("YouTube auth invalide pour StyleDirector")
                break
            except Exception as exc:
                logger.warning("Listing concurrent %s : %s", comp.handle_or_url, exc)
                continue
            for vid in videos:
                url = vid.get("url")
                if url and url not in competitor_urls:
                    competitor_urls.append(str(url))

        if len(competitor_urls) < max_competitor and channel.niche_prompt:
            try:
                landscape = await discover_youtube_landscape(
                    channel.niche_prompt,
                    token,
                    max_videos=max_competitor - len(competitor_urls),
                )
                for vid in landscape.get("top_videos", []):
                    vid_id = vid.get("video_id")
                    if vid_id:
                        url = f"https://www.youtube.com/watch?v={vid_id}"
                        if url not in competitor_urls:
                            competitor_urls.append(url)
            except YouTubeAuthError:
                pass
            except Exception as exc:
                logger.warning("discover_youtube_landscape : %s", exc)

        own_urls = await self._own_channel_video_urls(channel.id, limit=max_own)

        youtube_top = market.get("youtube_top_videos") or []
        for vid in youtube_top:
            if len(competitor_urls) >= max_competitor:
                break
            vid_id = vid.get("video_id") if isinstance(vid, dict) else None
            if vid_id:
                url = f"https://www.youtube.com/watch?v={vid_id}"
                if url not in competitor_urls:
                    competitor_urls.append(url)

        combined = competitor_urls[:max_competitor] + own_urls[:max_own]
        return combined[:max_refs]

    async def _own_channel_video_urls(
        self,
        channel_id: uuid.UUID,
        *,
        limit: int,
    ) -> list[str]:
        if limit <= 0:
            return []

        async with AsyncSessionFactory() as session:
            result = await session.execute(
                select(Publication, Video, Analytics.views)
                .join(Video, Publication.video_id == Video.id)
                .outerjoin(Analytics, Analytics.publication_id == Publication.id)
                .where(
                    Publication.channel_id == channel_id,
                    Publication.status == "published",
                )
                .order_by(Analytics.views.desc().nullslast())
                .limit(limit * 2)
            )
            rows = list(result.all())

        urls: list[str] = []
        for pub, video, _views in rows:
            if len(urls) >= limit:
                break
            if pub.platform_url:
                urls.append(str(pub.platform_url))
            elif pub.platform == "youtube" and pub.platform_video_id:
                urls.append(f"https://www.youtube.com/watch?v={pub.platform_video_id}")
            elif video.local_path and Path(video.local_path).is_file():
                urls.append(f"file://{Path(video.local_path).resolve()}")
        return urls

    async def _resolve_local_paths(self, refs: list[str]) -> list[Path]:
        paths: list[Path] = []
        style_cfg = load_style_config()
        max_clip_s = int(style_cfg.get("max_clip_duration_s", 180))

        for ref in refs:
            if ref.startswith("file://"):
                path = Path(ref.removeprefix("file://"))
                if path.is_file():
                    paths.append(path)
                continue
            path = await download_reference_video(ref, max_clip_s=max_clip_s)
            if path is not None:
                paths.append(path)

        return paths
