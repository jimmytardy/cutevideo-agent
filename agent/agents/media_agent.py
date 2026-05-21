from __future__ import annotations

import asyncio
import logging
import uuid
from pathlib import Path

from agent.core.base_agent import BaseAgent
from agent.core.config import settings
from agent.core.database import AsyncSessionFactory, MediaAsset, Scenario

logger = logging.getLogger(__name__)

IMAGES_PER_SEGMENT = 4
MIN_WIDTH_PX = 1280


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
        all_assets: list[MediaAsset] = []

        tasks = [
            self._process_segment(ctx, segment, sources)
            for segment in segments
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, list):
                all_assets.extend(result)
            elif isinstance(result, Exception):
                logger.warning("Erreur segment : %s", result)

        return all_assets

    async def _process_segment(
        self, ctx: "PipelineContext", segment: dict, sources: list[str]
    ) -> list[MediaAsset]:
        keywords = segment.get("search_keywords", [])
        period = segment.get("historical_period", "")
        order = segment.get("order", 0)

        candidates: list[dict] = []
        for source in sources:
            try:
                found = await self._search_source(source, keywords, period)
                candidates.extend(found)
                if len(candidates) >= IMAGES_PER_SEGMENT * 2:
                    break
            except Exception as e:
                logger.warning("Source %s échouée pour segment %d : %s", source, order, e)

        selected = candidates[:IMAGES_PER_SEGMENT]
        assets: list[MediaAsset] = []

        output_dir = Path(f"./tmp/{ctx.project_id}/media/segment_{order:02d}")
        output_dir.mkdir(parents=True, exist_ok=True)

        async with AsyncSessionFactory() as session:
            for item in selected:
                local_path = await self._download_asset(item, output_dir)
                asset = MediaAsset(
                    project_id=ctx.project_id,
                    segment_order=order,
                    source=item.get("source"),
                    source_url=item.get("url"),
                    local_path=str(local_path) if local_path else None,
                    license=item.get("license"),
                    attribution=item.get("attribution"),
                    asset_type="image",
                    selected=True,
                )
                session.add(asset)
                assets.append(asset)
            await session.commit()

        logger.info("Segment %d : %d médias trouvés", order, len(assets))
        return assets

    async def _search_source(
        self, source: str, keywords: list[str], period: str
    ) -> list[dict]:
        from agent.skills.media_sources import wikimedia, gallica, europeana, unsplash, pexels

        source_map = {
            "wikimedia": wikimedia.search,
            "gallica": gallica.search,
            "europeana": europeana.search,
            "unsplash": unsplash.search,
            "pexels": pexels.search,
        }
        fn = source_map.get(source)
        if fn is None:
            return []
        return await fn(keywords, period)

    @staticmethod
    async def _download_asset(item: dict, output_dir: Path) -> Path | None:
        import aiohttp
        url = item.get("url")
        if not url:
            return None
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
