from __future__ import annotations



import asyncio

import logging

import shutil

from pathlib import Path



from sqlalchemy import select



from agent.core.base_agent import BaseAgent

from agent.core.database import AsyncSessionFactory, Video

from agent.core.short_format import effective_short_max_duration_s

from agent.core.video_paths import resolve_video_local_path

from agent.agents.clipper_agent import ClipCandidate



logger = logging.getLogger(__name__)



PLATFORM_CONFIG = {

    "youtube": (120, "./output/shorts/youtube"),

    "tiktok": (120, "./output/shorts/tiktok"),

    "instagram": (120, "./output/shorts/instagram"),

}





class ShortEditorAgent(BaseAgent):

    """Agent 8 — Éditeur shorts : versions 9:16 par plateforme activée."""



    name = "short_editor_agent"



    def _active_platforms(self, ctx: "PipelineContext") -> list[tuple[str, int, str]]:

        enabled = set(ctx.channel_config.enabled_platforms)
        effective_max = effective_short_max_duration_s(
            ctx.target_duration_seconds,
            ctx.channel_config,
        )

        return [

            (platform, min(max_d, effective_max), out_dir)

            for platform, (max_d, out_dir) in PLATFORM_CONFIG.items()

            if platform in enabled

        ]



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



    async def run_platform_exports(self, ctx: "PipelineContext") -> list[Video]:

        """Exporte un short_master vers chaque plateforme activée (mode shorts_only)."""

        run = await self.start_run(ctx.project_id, {"mode": "platform_exports"})

        try:

            source = await self._load_export_source(ctx)

            if not source:

                await self.end_run(run, {"shorts_count": 0})

                return []



            source_path = await resolve_video_local_path(source)

            if not source_path or not source_path.exists():

                logger.warning("Source export introuvable pour le projet %s", ctx.project_id)

                await self.end_run(run, {"shorts_count": 0})

                return []



            videos: list[Video] = []

            for platform, max_d, out_dir in self._active_platforms(ctx):

                output_dir = Path(out_dir)

                output_dir.mkdir(parents=True, exist_ok=True)

                output_path = output_dir / f"{ctx.project_id}_{platform}.mp4"

                duration = min(source.duration_s or max_d, max_d)

                trimmed = (source.duration_s or 0) > max_d



                if trimmed:

                    from agent.skills.video.shorts import create_short

                    duration = await create_short(

                        source_path=source_path,

                        output_path=output_path,

                        start_s=0,

                        duration_s=max_d,

                        platform=platform,

                    )

                else:

                    shutil.copy2(source_path, output_path)



                async with AsyncSessionFactory() as session:

                    video = Video(

                        project_id=ctx.project_id,

                        video_type=f"short_{platform}",

                        local_path=str(output_path),

                        duration_s=duration,

                        iteration=ctx.iteration,

                        status="draft",

                    )

                    session.add(video)

                    await session.commit()

                    await session.refresh(video)



                from agent.core.storage import persist_video_to_storage



                video = await persist_video_to_storage(

                    video, ctx.channel_slug, output_path, delete_local=False

                )



                if trimmed and ctx.channel_config.subtitles.enabled:

                    from agent.agents.subtitle_agent import SubtitleAgent

                    await SubtitleAgent().burn_subtitles_for_video(ctx, video)



                videos.append(video)



            await self.end_run(run, {"shorts_count": len(videos)})

            return videos

        except Exception as e:

            await self.fail_run(run, e)

            raise



    async def run_native_exports(self, ctx: "PipelineContext") -> list[Video]:

        """Exporte chaque short_native_* vers les plateformes activées."""

        run = await self.start_run(ctx.project_id, {"mode": "native_exports"})

        try:

            masters = await self._load_native_masters(ctx)

            if not masters:

                await self.end_run(run, {"shorts_count": 0})

                return []



            videos: list[Video] = []

            for master in masters:

                exported = await self._export_native_master(ctx, master)

                videos.extend(exported)



            await self.end_run(run, {"shorts_count": len(videos)})

            return videos

        except Exception as e:

            await self.fail_run(run, e)

            raise



    async def _load_native_masters(self, ctx: "PipelineContext") -> list[Video]:

        async with AsyncSessionFactory() as session:

            result = await session.execute(

                select(Video)

                .where(

                    Video.project_id == ctx.project_id,

                    Video.video_type.like("short_native_%"),

                )

                .order_by(Video.video_type)

            )

            return list(result.scalars().all())



    async def _export_native_master(self, ctx: "PipelineContext", master: Video) -> list[Video]:

        import re

        import shutil



        from agent.skills.video.shorts import create_short



        match = re.search(r"short_native_(\d+)$", master.video_type or "")

        short_idx = match.group(1) if match else "00"



        source_path = await resolve_video_local_path(master)

        if not source_path or not source_path.exists():

            logger.warning("Master natif introuvable : %s", master.video_type)

            return []



        videos: list[Video] = []

        for platform, max_d, out_dir in self._active_platforms(ctx):

            output_dir = Path(out_dir)

            output_dir.mkdir(parents=True, exist_ok=True)

            output_path = output_dir / f"{ctx.project_id}_native{short_idx}_{platform}.mp4"

            duration = min(master.duration_s or max_d, max_d)

            trimmed = (master.duration_s or 0) > max_d



            if trimmed:

                duration = await create_short(

                    source_path=source_path,

                    output_path=output_path,

                    start_s=0,

                    duration_s=max_d,

                    platform=platform,

                )

            else:

                shutil.copy2(source_path, output_path)



            async with AsyncSessionFactory() as session:

                video = Video(

                    project_id=ctx.project_id,

                    video_type=f"short_{platform}_native_{short_idx}",

                    local_path=str(output_path),

                    duration_s=duration,

                    iteration=master.iteration,

                    status="draft",

                )

                session.add(video)

                await session.commit()

                await session.refresh(video)



            from agent.core.storage import persist_video_to_storage



            video = await persist_video_to_storage(

                video, ctx.channel_slug, output_path, delete_local=False

            )



            if trimmed and ctx.channel_config.subtitles.enabled:

                from agent.agents.subtitle_agent import SubtitleAgent



                await SubtitleAgent().burn_subtitles_for_video(ctx, video)



            videos.append(video)



        return videos



    async def _load_export_source(self, ctx: "PipelineContext") -> Video | None:

        async with AsyncSessionFactory() as session:

            result = await session.execute(

                select(Video)

                .where(

                    Video.project_id == ctx.project_id,

                    Video.video_type == "short_master",

                )

                .order_by(Video.iteration.desc(), Video.created_at.desc())

                .limit(1)

            )

            source = result.scalars().first()

            if source:

                return source



            result = await session.execute(

                select(Video)

                .where(

                    Video.project_id == ctx.project_id,

                    Video.video_type == "long",

                )

                .order_by(Video.iteration.desc(), Video.created_at.desc())

                .limit(1)

            )

            return result.scalars().first()



    async def _load_source_long_video(self, ctx: "PipelineContext") -> Video | None:

        async with AsyncSessionFactory() as session:

            for video_type in ("long", "short_master"):

                result = await session.execute(

                    select(Video)

                    .where(

                        Video.project_id == ctx.project_id,

                        Video.video_type == video_type,

                    )

                    .order_by(Video.iteration.desc(), Video.created_at.desc())

                    .limit(1)

                )

                video = result.scalars().first()

                if video is not None:

                    return video

        return None



    async def _produce_all_shorts(

        self, ctx: "PipelineContext", clips: list[ClipCandidate]

    ) -> list[Video]:

        source_video = await self._load_source_long_video(ctx)



        if not source_video:

            logger.warning("Aucune vidéo longue trouvée pour le projet %s", ctx.project_id)

            return []



        source_path = await resolve_video_local_path(source_video)

        if not source_path or not source_path.exists():

            logger.warning("Fichier source long introuvable pour le projet %s", ctx.project_id)

            return []



        tasks = [

            self._produce_clip_all_platforms(ctx, clip, source_path, idx)

            for idx, clip in enumerate(clips)

        ]

        from agent.core.concurrency import bounded_gather

        results = await bounded_gather(*tasks, return_exceptions=True)



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

        from agent.skills.video.montage_profile import dynamic_recut_enabled
        from agent.skills.video.shorts import create_short



        videos: list[Video] = []

        for platform, max_duration_s, output_dir_str in self._active_platforms(ctx):

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

                dynamic_recut=dynamic_recut_enabled(
                    channel_raw_config=dict(ctx.channel.config or {}),
                ),

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



            video = await persist_video_to_storage(

                video, ctx.channel_slug, output_path, delete_local=False

            )

            videos.append(video)



        return videos


