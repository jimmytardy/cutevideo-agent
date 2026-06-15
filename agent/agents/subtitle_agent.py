from __future__ import annotations



import logging

from pathlib import Path



from sqlalchemy import select



from agent.core.base_agent import BaseAgent

from agent.core.config import load_agent_config

from agent.core.database import AsyncSessionFactory, AudioFile, Video

from agent.core.video_paths import resolve_video_local_path



logger = logging.getLogger(__name__)





class SubtitleAgent(BaseAgent):

    """Agent 5 — Sous-titreur : burn-in karaoké pour shorts, .srt sidecar pour longues."""



    name = "subtitle_agent"



    async def run(self, ctx: "PipelineContext", video: Video) -> Path | None:  # type: ignore[override]

        run = await self.start_run(

            ctx.project_id, {"video_id": str(video.id)}, iteration=ctx.iteration

        )

        try:

            result_path = await self.burn_subtitles_for_video(ctx, video)

            await self.end_run(

                run,

                {

                    "output_path": str(result_path) if result_path else None,

                    "burn_in": result_path is not None and result_path.suffix == ".mp4",

                },

            )

            return result_path

        except Exception as e:

            await self.fail_run(run, e)

            raise



    async def burn_subtitles_for_video(

        self, ctx: "PipelineContext", video: Video

    ) -> Path | None:

        """Génère sous-titres (burn-in ou SRT) pour une vidéo."""

        return await self._generate_subtitles(ctx, video)



    async def _generate_subtitles(self, ctx: "PipelineContext", video: Video) -> Path | None:

        output_dir = Path(f"./tmp/{ctx.project_id}")

        output_dir.mkdir(parents=True, exist_ok=True)



        whisper_cfg = load_agent_config().get("whisper", {})

        model_name = str(whisper_cfg.get("model", "large-v3"))

        language = str(whisper_cfg.get("language", "fr"))



        audio_paths = await self._resolve_audio_paths(ctx, video, output_dir)

        if not audio_paths:

            logger.warning("Aucune source audio pour sous-titres — projet %s", ctx.project_id)

            return None



        if self._should_burn_in(ctx, video):

            return await self._burn_karaoke_subtitles(

                ctx, video, audio_paths, output_dir, model_name, language

            )



        from agent.skills.audio.whisper_utils import transcribe_to_words

        from agent.skills.video.viral_subtitles import group_words_into_lines, write_srt_from_lines



        words = await transcribe_to_words(audio_paths, model_name=model_name, language=language)

        if not words:

            logger.warning("Aucun mot transcrit pour SRT — projet %s", ctx.project_id)

            return None



        subs_cfg = ctx.channel_config.subtitles

        lines = group_words_into_lines(

            words,

            max_words=subs_cfg.max_words_per_line,

            pause_threshold_s=subs_cfg.pause_threshold_ms / 1000.0,

        )

        if not lines:

            return None



        lines = await self._proofread_subtitle_lines(lines)



        srt_path = output_dir / "subtitles.srt"

        write_srt_from_lines(lines, srt_path)

        logger.info("Sous-titres SRT générés : %s", srt_path)

        return srt_path



    async def _proofread_subtitle_lines(

        self,

        lines: list,

    ) -> list:

        from agent.skills.subtitle.subtitle_proofreader import proofread_subtitle_segments

        from agent.skills.video.viral_subtitles import SubtitleLine



        segments = [

            {

                "start": line.start,

                "end": line.end,

                "text": " ".join(w.word for w in line.words),

            }

            for line in lines

        ]

        corrected = await proofread_subtitle_segments(

            segments,

            call_llm=lambda prompt, **kw: self._call_claude(prompt, **kw),

        )

        updated: list[SubtitleLine] = []

        for line, seg in zip(lines, corrected, strict=True):

            words = list(line.words)

            parts = str(seg.get("text", "")).split()

            if len(parts) == len(words):

                for w, part in zip(words, parts, strict=True):

                    w.word = part

            elif parts:

                words[0].word = " ".join(parts)

                for w in words[1:]:

                    w.word = ""

            updated.append(SubtitleLine(words=words))

        return updated



    async def _resolve_audio_paths(

        self,

        ctx: "PipelineContext",

        video: Video,

        output_dir: Path,

    ) -> list[Path]:

        async with AsyncSessionFactory() as session:

            result = await session.execute(

                select(AudioFile)

                .where(AudioFile.project_id == ctx.project_id)

                .order_by(AudioFile.segment_order)

            )

            audio_files = result.scalars().all()



        tts_paths = [

            Path(af.local_path)

            for af in audio_files

            if af.local_path and Path(af.local_path).exists()

        ]

        if tts_paths:

            return tts_paths



        video_path = await resolve_video_local_path(video)

        if not video_path or not video_path.exists():

            return []



        from agent.skills.audio.whisper_utils import extract_audio_from_video



        wav_path = output_dir / f"{video.id}_fallback.wav"

        extracted = await extract_audio_from_video(video_path, wav_path)

        return [extracted] if extracted else []



    @staticmethod

    def _should_burn_in(ctx: "PipelineContext", video: Video) -> bool:

        if not ctx.channel_config.subtitles.enabled:

            return False

        if ctx.channel_config.production_mode != "shorts_only":

            return False

        vtype = video.video_type or ""

        return vtype == "short_master" or vtype.startswith("short_")



    async def _burn_karaoke_subtitles(

        self,

        ctx: "PipelineContext",

        video: Video,

        audio_paths: list[Path],

        output_dir: Path,

        model_name: str,

        language: str,

    ) -> Path | None:

        from agent.skills.audio.whisper_utils import transcribe_to_words, transcribe_video_to_words

        from agent.skills.video.viral_subtitles import (

            burn_ass_subtitles,

            group_words_into_lines,

            style_from_config,

            write_ass_file,

            write_srt_from_lines,

        )



        video_path = await resolve_video_local_path(video)

        if not video_path or not video_path.exists():

            logger.warning("Vidéo introuvable pour burn-in : %s", video.local_path)

            return None



        subs_cfg = ctx.channel_config.subtitles



        words = await transcribe_to_words(audio_paths, model_name=model_name, language=language)

        if not words:

            words = await transcribe_video_to_words(

                video_path, output_dir, model_name=model_name, language=language

            )

        if not words:

            logger.warning("Aucun mot transcrit pour le projet %s", ctx.project_id)

            return None



        lines = group_words_into_lines(

            words,

            max_words=subs_cfg.max_words_per_line,

            pause_threshold_s=subs_cfg.pause_threshold_ms / 1000.0,

        )

        if not lines:

            logger.warning("Aucune ligne de sous-titre générée pour le projet %s", ctx.project_id)

            return None



        lines = await self._proofread_subtitle_lines(lines)



        style = style_from_config(subs_cfg)

        ass_path = output_dir / f"subtitles_{video.id}.ass"

        write_ass_file(lines, style, ass_path)



        srt_path = output_dir / f"subtitles_{video.id}.srt"

        write_srt_from_lines(lines, srt_path)



        output_path = video_path.with_stem(f"{video_path.stem}_subtitled")

        await burn_ass_subtitles(video_path, ass_path, output_path)



        if video_path != output_path and video_path.exists():

            video_path.unlink(missing_ok=True)



        async with AsyncSessionFactory() as session:

            db_video = await session.get(Video, video.id)

            if db_video:

                db_video.local_path = str(output_path)

                await session.commit()



        from agent.core.storage import persist_video_to_storage



        await persist_video_to_storage(

            video, ctx.channel_slug, output_path, delete_local=False

        )



        logger.info("Sous-titres karaoké incrustés : %s", output_path)

        return output_path


