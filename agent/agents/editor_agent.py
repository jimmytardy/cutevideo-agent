from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import select

from agent.core.base_agent import BaseAgent
from agent.core.config import settings
from agent.core.database import AsyncSessionFactory, AudioFile, MediaAsset, Scenario, Video

logger = logging.getLogger(__name__)


class EditorAgent(BaseAgent):
    """Agent 4 — Monteur vidéo : assemble images + voix (+ texte à l'écran)."""

    name = "editor_agent"

    async def run(self, ctx: "PipelineContext", scenario: Scenario | None = None) -> Video:  # type: ignore[override]
        run = await self.start_run(ctx.project_id, {"iteration": ctx.iteration})
        try:
            video = await self._assemble_video(ctx, scenario)
            await self.end_run(run, {"video_id": str(video.id), "path": video.local_path})
            return video
        except Exception as e:
            await self.fail_run(run, e)
            raise

    async def _assemble_video(self, ctx: "PipelineContext", scenario: Scenario | None) -> Video:
        from agent.skills.video.ffmpeg_utils import assemble_long_video, assemble_vertical_short

        async with AsyncSessionFactory() as session:
            media_result = await session.execute(
                select(MediaAsset)
                .where(MediaAsset.project_id == ctx.project_id, MediaAsset.selected == True)
                .order_by(MediaAsset.segment_order)
            )
            media_assets = list(media_result.scalars().all())

            audio_result = await session.execute(
                select(AudioFile)
                .where(AudioFile.project_id == ctx.project_id)
                .order_by(AudioFile.segment_order)
            )
            audio_files = list(audio_result.scalars().all())

        segment_meta: dict[int, dict] = {}
        segment_durations: dict[int, float] = {}
        if scenario and scenario.segments:
            for seg in scenario.segments:
                order = seg.get("order", 0)
                segment_meta[order] = {
                    "on_screen_text": seg.get("on_screen_text", ""),
                    "duration_s": seg.get("duration_s", 30),
                    "needs_voice": seg.get("needs_voice", True),
                }
                segment_durations[order] = float(seg.get("duration_s", 30))

        is_vertical = ctx.channel_config.production_mode == "shorts_only"

        if is_vertical:
            output_dir = Path("./output/shorts/master")
            output_dir.mkdir(parents=True, exist_ok=True)
            output_path = output_dir / f"{ctx.project_id}_v{ctx.iteration}.mp4"
            duration_s = await assemble_vertical_short(
                media_assets=media_assets,
                audio_files=audio_files,
                output_path=output_path,
                project_id=ctx.project_id,
                min_image_duration=ctx.channel_config.min_image_duration_s,
                segment_meta=segment_meta,
            )
            video_type = "short_master"
        else:
            output_dir = Path("./output/long")
            output_dir.mkdir(parents=True, exist_ok=True)
            output_path = output_dir / f"{ctx.project_id}_v{ctx.iteration}.mp4"
            duration_s = await assemble_long_video(
                media_assets=media_assets,
                audio_files=audio_files,
                output_path=output_path,
                project_id=ctx.project_id,
                min_image_duration=settings.min_image_duration_s,
                segment_durations=segment_durations,
            )
            video_type = "long"

        output_path = await self._maybe_mix_music(ctx, output_path)

        async with AsyncSessionFactory() as session:
            video = Video(
                project_id=ctx.project_id,
                video_type=video_type,
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
        logger.info("Vidéo assemblée (%s) : %s (%.1f s)", video_type, output_path, duration_s)
        return video

    async def _maybe_mix_music(self, ctx: "PipelineContext", video_path: Path) -> Path:
        """Tente de mixer une musique de fond ; retourne le chemin original en cas d'échec."""
        from agent.skills.audio.music_fetcher import fetch_background_music
        from agent.skills.video.ffmpeg_utils import mix_background_music

        try:
            music_path = await fetch_background_music(
                theme_category=ctx.channel_config.music_theme,
                output_dir=Path(f"./tmp/{ctx.project_id}/music"),
            )
            if not music_path:
                return video_path

            mixed_path = video_path.with_stem(video_path.stem + "_music")
            await mix_background_music(video_path, music_path, mixed_path)
            video_path.unlink(missing_ok=True)
            return mixed_path

        except Exception as e:
            logger.warning("Musique de fond ignorée (erreur) : %s", e)
            return video_path
