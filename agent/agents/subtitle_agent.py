from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import select

from agent.core.base_agent import BaseAgent
from agent.core.database import AsyncSessionFactory, AudioFile, Video

logger = logging.getLogger(__name__)


class SubtitleAgent(BaseAgent):
    """Agent 5 — Sous-titreur : génère .srt pour vidéo longue, burn-in pour shorts."""

    name = "subtitle_agent"

    async def run(self, ctx: "PipelineContext", video: Video) -> Path | None:  # type: ignore[override]
        run = await self.start_run(ctx.project_id, {"video_id": str(video.id)})
        try:
            srt_path = await self._generate_subtitles(ctx, video)
            await self.end_run(run, {"srt_path": str(srt_path) if srt_path else None})
            return srt_path
        except Exception as e:
            await self.fail_run(run, e)
            raise

    async def _generate_subtitles(self, ctx: "PipelineContext", video: Video) -> Path | None:
        from agent.skills.audio.whisper_utils import transcribe_to_srt

        async with AsyncSessionFactory() as session:
            result = await session.execute(
                select(AudioFile)
                .where(AudioFile.project_id == ctx.project_id)
                .order_by(AudioFile.segment_order)
            )
            audio_files = result.scalars().all()

        if not audio_files:
            logger.warning("Aucun fichier audio trouvé pour le projet %s", ctx.project_id)
            return None

        output_dir = Path(f"./tmp/{ctx.project_id}")
        output_dir.mkdir(parents=True, exist_ok=True)
        srt_path = output_dir / "subtitles.srt"

        audio_paths = [Path(af.local_path) for af in audio_files if af.local_path]
        await transcribe_to_srt(audio_paths, srt_path)

        logger.info("Sous-titres générés : %s", srt_path)
        return srt_path
