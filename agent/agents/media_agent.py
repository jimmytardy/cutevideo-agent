from __future__ import annotations

import asyncio
import json
import logging
import uuid
from pathlib import Path
from typing import Any

import anthropic

from agent.core.base_agent import BaseAgent
from agent.core.config import settings
from agent.core.database import AsyncSessionFactory, MediaAsset, Scenario

logger = logging.getLogger(__name__)


class MediaAgent(BaseAgent):
    """Agent 2 — Chercheur média : trouve les images/vidéos libres de droits."""

    name = "media_agent"

    async def run(self, ctx: "PipelineContext", scenario: Scenario) -> list[MediaAsset]:  # type: ignore[override]
        run = await self.start_run(ctx.project_id, {"scenario_id": str(scenario.id)})
        try:
            assets = await self._search_all_segments(ctx, scenario)
            await self.end_run(run, {"assets_count": len(assets)})
            return assets
        except Exception as e:
            await self.fail_run(run, e)
            raise

    async def _search_all_segments(
        self, ctx: "PipelineContext", scenario: Scenario
    ) -> list[MediaAsset]:
        segments = scenario.segments or []
        sources = ctx.channel_config.media_source_priority
        ms_cfg = ctx.channel_config.media_sources
        ai_cfg = ctx.channel_config.ai_fallback
        all_assets: list[MediaAsset] = []

        self._ai_images_used = 0
        self._runway_clips_used = 0

        tasks = [
            self._process_segment(ctx, segment, sources, ms_cfg, ai_cfg) for segment in segments
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        failed_segments = []
        for i, result in enumerate(results):
            if isinstance(result, list):
                all_assets.extend(result)
            elif isinstance(result, Exception):
                logger.warning("Erreur segment %d : %s", i, result)
                failed_segments.append(i)

        if failed_segments and len(failed_segments) == len(segments):
            raise RuntimeError(
                f"Tous les segments ont échoué ({len(failed_segments)}/{len(segments)}). "
                f"Dernière erreur : {results[-1]}"
            )
        if failed_segments:
            logger.warning(
                "%d/%d segments en erreur — pipeline continue avec %d assets",
                len(failed_segments), len(segments), len(all_assets),
            )

        return all_assets

    async def _process_segment(
        self,
        ctx: "PipelineContext",
        segment: dict,
        sources: list[str],
        ms_cfg: Any,
        ai_cfg: Any,
    ) -> list[MediaAsset]:
        keywords = segment.get("search_keywords", [])
        period = segment.get("historical_period", "")
        order = segment.get("order", 0)
        images_needed = ms_cfg.images_per_segment
        min_candidates = ms_cfg.min_candidates_per_segment

        # source_hint du segment (défini par le ScenarioAgent) en tête de liste,
        # puis les sources de la chaîne en fallback (sans doublons)
        hint = segment.get("source_hint") or []
        if hint:
            seen = set(hint)
            effective_sources = list(hint) + [s for s in sources if s not in seen]
        else:
            effective_sources = sources

        candidates = await self._search_with_fallback(
            effective_sources, keywords, period, segment, min_candidates
        )
        candidates = self._dedupe_and_filter(candidates, ms_cfg.min_width_px)

        output_dir = Path(f"./tmp/{ctx.project_id}/media/segment_{order:02d}")

        # Tier 2: AI image fallback
        if len(candidates) < images_needed and ms_cfg.enable_ai_fallback and ai_cfg.enabled:
            missing = images_needed - len(candidates)
            ai_prompt = f"{segment.get('title', '')} — {' '.join(keywords[:3])}"
            aspect_ratio = (
                "9:16" if ctx.channel_config.production_mode == "shorts_only" else "16:9"
            )
            max_segment_ai = min(missing, ai_cfg.max_images_per_segment)
            for _ in range(max_segment_ai):
                if not await self._can_generate_ai_image(ctx, ai_cfg):
                    break
                ai_item = await self._generate_ai_fallback(
                    ai_prompt,
                    output_dir,
                    ctx.theme_category,
                    ctx.channel_config.editorial_tone,
                    ai_cfg=ai_cfg,
                    aspect_ratio=aspect_ratio,
                )
                if ai_item:
                    candidates.append(ai_item)
                    self._ai_images_used += 1
                    await self._record_ai_image_usage(ctx)

        # Tier 3: Runway video generation (when still not enough candidates)
        runway_cfg = ctx.channel_config.runway
        if (
            len(candidates) < images_needed
            and runway_cfg.enabled
            and self._runway_clips_used < runway_cfg.max_clips_per_video
        ):
            runway_prompt = (
                f"{segment.get('title', '')} — {' '.join(keywords[:4])}"
            )
            runway_item = await self._generate_runway_clip(
                runway_prompt, output_dir, runway_cfg, ctx
            )
            if runway_item:
                candidates.append(runway_item)
                self._runway_clips_used += 1

        selected = candidates[:images_needed]
        assets: list[MediaAsset] = []
        output_dir.mkdir(parents=True, exist_ok=True)

        async with AsyncSessionFactory() as session:
            for item in selected:
                is_video = item.get("asset_type") == "video"
                local_path = (
                    Path(item["local_generated"])
                    if is_video
                    else await self._download_asset(item, output_dir)
                )
                asset = MediaAsset(
                    project_id=ctx.project_id,
                    segment_order=order,
                    source=item.get("source"),
                    source_url=item.get("url"),
                    local_path=str(local_path) if local_path else item.get("local_generated"),
                    license=item.get("license"),
                    attribution=item.get("attribution"),
                    asset_type="video" if is_video else "image",
                    selected=True,
                )
                session.add(asset)
                assets.append(asset)
            await session.commit()

        logger.info("Segment %d : %d médias trouvés", order, len(assets))
        return assets

    async def _generate_runway_clip(
        self,
        prompt: str,
        output_dir: Path,
        runway_cfg: Any,
        ctx: "PipelineContext",
    ) -> dict | None:
        from agent.skills.media_sources.runway import generate_video_clip

        return await generate_video_clip(
            prompt,
            output_dir,
            runway_cfg=runway_cfg,
            channel_id=str(ctx.channel_id),
            timezone=ctx.channel_config.timezone,
        )

    async def _search_with_fallback(
        self,
        sources: list[str],
        keywords: list[str],
        period: str,
        segment: dict,
        min_candidates: int,
    ) -> list[dict]:
        candidates: list[dict] = []

        for source in sources:
            try:
                found = await self._search_source(source, keywords, period)
                candidates.extend(found)
                if len(candidates) >= min_candidates * 2:
                    break
            except Exception as e:
                logger.warning("Source %s échouée : %s", source, e)

        if len(candidates) >= min_candidates:
            return candidates

        simplified = [[k] for k in keywords[:3] if k]
        for kw_list in simplified:
            for source in sources[:2]:
                try:
                    found = await self._search_source(source, kw_list, "")
                    candidates.extend(found)
                except Exception:
                    pass
            if len(candidates) >= min_candidates:
                return self._dedupe_and_filter(candidates, 0)

        alt_keywords = await self._llm_alternative_keywords(segment)
        for kw_list in alt_keywords:
            for source in sources:
                try:
                    found = await self._search_source(source, kw_list, "")
                    candidates.extend(found)
                except Exception:
                    pass
            if len(candidates) >= min_candidates:
                break

        return candidates

    async def _llm_alternative_keywords(self, segment: dict) -> list[list[str]]:
        narration = segment.get("narration_text", "")[:800]
        title = segment.get("title", "")
        prompt = (
            f"Segment vidéo : {title}\n{narration}\n"
            "Génère 3 listes de 2-4 mots-clés de recherche image (FR/EN) pour trouver des visuels libres. "
            'Retourne UNIQUEMENT JSON : {"queries": [["kw1","kw2"], ...]}'
        )

        try:
            client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
            msg = await client.messages.create(
                model="claude-sonnet-4-5",
                max_tokens=256,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = msg.content[0].text.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
            data = json.loads(raw)
            queries = data.get("queries", [])
            return [[str(k) for k in q] for q in queries if isinstance(q, list)]
        except Exception as e:
            logger.warning("LLM keywords fallback échoué : %s", e)
            return []

    @staticmethod
    def _dedupe_and_filter(candidates: list[dict], min_width: int) -> list[dict]:
        seen: set[str] = set()
        filtered: list[dict] = []
        for item in candidates:
            url = item.get("url", "")
            if not url or url in seen:
                continue
            width = item.get("width")
            if min_width and width and int(width) < min_width:
                continue
            seen.add(url)
            filtered.append(item)
        return filtered

    async def _search_source(
        self, source: str, keywords: list[str], period: str
    ) -> list[dict]:
        from agent.skills.media_sources import (
            europeana,
            gallica,
            internet_archive,
            pexels,
            pixabay,
            unsplash,
            wikimedia,
        )

        source_map = {
            "wikimedia": wikimedia.search,
            "gallica": gallica.search,
            "europeana": europeana.search,
            "unsplash": unsplash.search,
            "pexels": pexels.search,
            "pixabay": pixabay.search,
            "internet_archive": internet_archive.search,
        }
        fn = source_map.get(source)
        if fn is None:
            return []
        return await fn(keywords, period)

    async def _can_generate_ai_image(self, ctx: "PipelineContext", ai_cfg: Any) -> bool:
        if ai_cfg.plan.value == "off" or not ai_cfg.enabled:
            return False
        if self._ai_images_used >= ai_cfg.max_ai_images_per_video:
            logger.info("Plafond IA vidéo atteint (%d)", ai_cfg.max_ai_images_per_video)
            return False
        if ai_cfg.max_ai_images_per_week is None:
            return True
        from agent.core.ai_image_budget import get_weekly_ai_image_count

        weekly = await get_weekly_ai_image_count(
            str(ctx.channel_id),
            timezone=ctx.channel_config.timezone,
        )
        if weekly >= ai_cfg.max_ai_images_per_week:
            logger.info("Plafond IA hebdo chaîne atteint (%d)", ai_cfg.max_ai_images_per_week)
            return False
        return True

    async def _record_ai_image_usage(self, ctx: "PipelineContext") -> None:
        from agent.core.ai_image_budget import increment_weekly_ai_image_count

        await increment_weekly_ai_image_count(
            str(ctx.channel_id),
            timezone=ctx.channel_config.timezone,
        )

    async def _generate_ai_fallback(
        self,
        prompt: str,
        output_dir: Path,
        theme_category: str,
        editorial_tone: str,
        *,
        ai_cfg: Any,
        aspect_ratio: str = "16:9",
    ) -> dict | None:
        from agent.skills.media_sources.ai_image import generate_image

        return await generate_image(
            prompt,
            output_dir,
            ai_cfg=ai_cfg,
            theme_category=theme_category,
            editorial_tone=editorial_tone,
            aspect_ratio=aspect_ratio,
        )

    @staticmethod
    async def _download_asset(item: dict, output_dir: Path) -> Path | None:
        if item.get("local_generated"):
            return Path(item["local_generated"])

        import aiohttp

        url = item.get("url")
        if not url or url.startswith("/"):
            return Path(url) if url and Path(url).exists() else None
        filename = url.split("/")[-1].split("?")[0] or "image.jpg"
        dest = output_dir / filename
        if dest.exists():
            return dest
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    if resp.status == 200:
                        dest.write_bytes(await resp.read())
                        return dest
        except Exception as e:
            logger.warning("Téléchargement échoué %s : %s", url, e)
        return None
