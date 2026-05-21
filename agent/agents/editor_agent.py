from __future__ import annotations

import logging
import uuid
from pathlib import Path

from sqlalchemy import select

from agent.core.base_agent import BaseAgent
from agent.core.config import settings
from agent.core.database import AsyncSessionFactory, AudioFile, MediaAsset, Video

logger = logging.getLogger(__name__)


class EditorAgent(BaseAgent):
    """Agent 4 — Monteur vidéo longue : assemble images + voix + musique."""

    name = "editor_agent"

    async def run(self, ctx: "PipelineContext") -> Video:  # type: ignore[override]
        run = await self.start_run(ctx.project_id, {"iteration": ctx.iteration})
        try:
            video = await self._assemble_video(ctx)
            await self.end_run(run, {"video_id": str(video.id), "path": video.local_path})
            return video
        except Exception as e:
            await self.fail_run(run, e)
            raise

    async def _assemble_video(self, ctx: "PipelineContext") -> Video:
        from agent.skills.video.ffmpeg_utils import assemble_long_video

        async with AsyncSessionFactory() as session:
            media_result = await session.execute(
                select(MediaAsset)
                .where(MediaAsset.project_id == ctx.project_id, MediaAsset.selected == True)
                .order_by(MediaAsset.segment_order)
            )
            media_assets = media_result.scalars().all()

            audio_result = await session.execute(
                select(AudioFile)
                .where(AudioFile.project_id == ctx.project_id)
                .order_by(AudioFile.segment_order)
            )
            audio_files = audio_result.scalars().all()

        output_dir = Path(f"./output/long")
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{ctx.project_id}_v{ctx.iteration}.mp4"

        duration_s = await assemble_long_video(
            media_assets=list(media_assets),
            audio_files=list(audio_files),
            output_path=output_path,
            project_id=ctx.project_id,
            min_image_duration=settings.min_image_duration_s,
        )

        async with AsyncSessionFactory() as session:
            video = Video(
                project_id=ctx.project_id,
                video_type="long",
                local_path=str(output_path),
                duration_s=duration_s,
                iteration=ctx.iteration,
                status="draft",
            )
            session.add(video)
            await session.commit()
            await session.refresh(video)

        from agent.core.storage import persist_video_to_storage

        video = await persist_video_to_storage(video, ctx.channel_slug, output_path)
        logger.info("Vidéo longue assemblée : %s (%.1f s)", output_path, duration_s)
        return video
