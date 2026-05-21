from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from sqlalchemy import select

from agent.core.base_agent import BaseAgent
from agent.core.database import AsyncSessionFactory, Video
from agent.agents.clipper_agent import ClipCandidate

logger = logging.getLogger(__name__)

PLATFORMS = [
    ("youtube", 60, "./output/shorts/youtube"),
    ("tiktok", 90, "./output/shorts/tiktok"),
    ("instagram", 90, "./output/shorts/instagram"),
]


class ShortEditorAgent(BaseAgent):
    """Agent 8 — Éditeur shorts : produit 3 versions 9:16 pour chaque clip."""

    name = "short_editor_agent"

    async def run(  # type: ignore[override]
        self, ctx: "PipelineContext", clips: list[ClipCandidate]
    ) -> list[Video]:
        run = await self.start_run(ctx.project_id, {"clips_count": len(clips)})
        try:
            shorts = await self._produce_all_shorts(ctx, clips)
            await self.end_run(run, {"shorts_count": len(shorts)})
            return shorts
        except Exception as e:
            await self.fail_run(run, e)
            raise

    async def _produce_all_shorts(
        self, ctx: "PipelineContext", clips: list[ClipCandidate]
    ) -> list[Video]:
        async with AsyncSessionFactory() as session:
            result = await session.execute(
                select(Video)
                .where(Video.project_id == ctx.project_id, Video.video_type == "long")
                .order_by(Video.created_at.desc())
            )
            source_video = result.scalar_one_or_none()

        if not source_video or not source_video.local_path:
            logger.warning("Aucune vidéo longue trouvée pour le projet %s", ctx.project_id)
            return []

        source_path = Path(source_video.local_path)
        tasks = [
            self._produce_clip_all_platforms(ctx, clip, source_path, idx)
            for idx, clip in enumerate(clips)
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        shorts: list[Video] = []
        for result in results:
            if isinstance(result, list):
                shorts.extend(result)
            elif isinstance(result, Exception):
                logger.warning("Erreur édition short : %s", result)

        return shorts

    async def _produce_clip_all_platforms(
        self,
        ctx: "PipelineContext",
        clip: ClipCandidate,
        source_path: Path,
        clip_idx: int,
    ) -> list[Video]:
        from agent.skills.video.shorts import create_short

        videos: list[Video] = []
        for platform, max_duration_s, output_dir_str in PLATFORMS:
            output_dir = Path(output_dir_str)
            output_dir.mkdir(parents=True, exist_ok=True)

            duration = min(clip.duration_s, max_duration_s)
            output_path = output_dir / f"{ctx.project_id}_clip{clip_idx:02d}.mp4"

            actual_duration = await create_short(
                source_path=source_path,
                output_path=output_path,
                start_s=clip.estimated_start_s,
                duration_s=duration,
                platform=platform,
                cta_text=clip.cta,
                hook_text=clip.hook,
            )

            async with AsyncSessionFactory() as session:
                video = Video(
                    project_id=ctx.project_id,
                    video_type=f"short_{platform}",
                    local_path=str(output_path),
                    duration_s=actual_duration,
                    iteration=ctx.iteration,
                    status="draft",
                )
                session.add(video)
                await session.commit()
                await session.refresh(video)

            from agent.core.storage import persist_video_to_storage

            video = await persist_video_to_storage(video, ctx.channel_slug, output_path)
            videos.append(video)
            logger.debug("Short %s clip %d créé : %s", platform, clip_idx, output_path)

        return videos
