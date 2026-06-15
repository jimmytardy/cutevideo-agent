from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import select

from typing import Any

from agent.core.base_agent import BaseAgent
from agent.core.database import AsyncSessionFactory, AudioFile, MediaAsset, Scenario, Video
from agent.agents.narrator_agent import segment_needs_music, segment_needs_voice

logger = logging.getLogger(__name__)


class EditorAgent(BaseAgent):
    """Agent 4 — Monteur vidéo : assemble images + voix (+ texte à l'écran)."""

    name = "editor_agent"

    async def run(self, ctx: "PipelineContext", scenario: Scenario | None = None) -> Video:  # type: ignore[override]
        run = await self.start_run(
            ctx.project_id, {"iteration": ctx.iteration}, iteration=ctx.iteration
        )
        try:
            video = await self._assemble_video(ctx, scenario)
            await self.end_run(run, {"video_id": str(video.id), "path": video.local_path})
            return video
        except Exception as e:
            await self.fail_run(run, e)
            raise

    async def run_derivation(
        self, ctx: "PipelineContext", plan: "DerivedShortPlan"
    ) -> Video:
        from agent.core.short_derivation import DerivedShortPlan
        from agent.skills.shorts.derivation import run_assembly_for_short_derivation

        run = await self.start_run(
            ctx.project_id,
            {"derivation_index": plan.index, "mode": "short_derivation"},
        )
        try:
            video = await run_assembly_for_short_derivation(self, ctx, plan)
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
                .order_by(MediaAsset.segment_order, MediaAsset.beat_index)
            )
            media_assets = list(media_result.scalars().all())

            audio_result = await session.execute(
                select(AudioFile)
                .where(AudioFile.project_id == ctx.project_id)
                .order_by(AudioFile.segment_order)
            )
            audio_files = list(audio_result.scalars().all())

        self._validate_media_assets(media_assets, scenario)

        segment_meta: dict[int, dict] = {}
        segment_durations: dict[int, float] = {}
        segment_beat_timelines = await self._build_segment_beat_timelines(
            scenario, media_assets, audio_files, ctx.channel_config
        )
        if scenario and scenario.segments:
            for seg in scenario.segments:
                order = seg.get("order", 0)
                needs_voice = segment_needs_voice(seg)
                needs_music = segment_needs_music(seg)
                segment_meta[order] = {
                    "on_screen_text": seg.get("on_screen_text", ""),
                    "duration_s": seg.get("duration_s", 30),
                    "needs_voice": needs_voice,
                    "needs_music": needs_music,
                    "mood": seg.get("mood", "calme"),
                    "strip_source_audio": seg.get("strip_source_audio", needs_voice),
                    "visual_optional": bool(seg.get("visual_optional", False)),
                }
                segment_durations[order] = float(seg.get("duration_s", 30))

        self._validate_audio_coverage(scenario, audio_files)

        is_vertical = ctx.channel_config.production_mode == "shorts_only"
        min_img = (
            ctx.channel_config.min_image_duration_short_s
            if is_vertical
            else ctx.channel_config.min_image_duration_s
        )

        if is_vertical:
            output_dir = Path("./output/shorts/master")
            output_dir.mkdir(parents=True, exist_ok=True)
            output_path = output_dir / f"{ctx.project_id}_v{ctx.iteration}.mp4"
            duration_s = await assemble_vertical_short(
                media_assets=media_assets,
                audio_files=audio_files,
                output_path=output_path,
                project_id=ctx.project_id,
                min_image_duration=min_img,
                segment_meta=segment_meta,
                segment_beat_timelines=segment_beat_timelines,
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
                min_image_duration=min_img,
                segment_durations=segment_durations,
                segment_meta=segment_meta,
                segment_beat_timelines=segment_beat_timelines,
            )
            video_type = "long"

        output_path = await self._mix_music_by_mood(ctx, output_path, segment_meta, duration_s)

        from agent.skills.video.ffmpeg_utils import assert_audio_has_signal

        has_narration = any(m.get("needs_voice") for m in segment_meta.values())
        await assert_audio_has_signal(
            output_path,
            min_mean_db=-50.0 if has_narration else -65.0,
            required=_scenario_requires_audio(segment_meta),
        )

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

        video = await persist_video_to_storage(
            video, ctx.channel_slug, output_path, delete_local=False
        )
        logger.info("Vidéo assemblée (%s) : %s (%.1f s)", video_type, output_path, duration_s)
        return video

    @staticmethod
    async def _build_segment_beat_timelines(
        scenario: Scenario | None,
        media_assets: list[MediaAsset],
        audio_files: list[AudioFile],
        channel_config: Any,
    ) -> dict[int, list]:
        from agent.core.visual_beats import (
            effective_min_duration,
            is_diagram_beat,
            parse_visual_beats,
        )
        from agent.skills.video.beat_timeline import (
            BeatTimelineEntry,
            compute_beat_timeline,
            word_segments_from_json,
        )
        from agent.skills.video.diagram_text_layout import analyze_diagram_text_layout

        if not scenario or not channel_config.visual_beats.enabled:
            return {}

        is_short = channel_config.production_mode == "shorts_only"
        audio_by_order = {(af.segment_order or 0): af for af in audio_files}
        assets_by_order: dict[int, list[MediaAsset]] = {}
        for asset in media_assets:
            order = asset.segment_order or 0
            assets_by_order.setdefault(order, []).append(asset)

        timelines: dict[int, list[BeatTimelineEntry]] = {}

        def min_for_beat(beat: Any) -> float:
            return effective_min_duration(beat, is_short=is_short, config=channel_config)

        for seg in scenario.segments or []:
            order = int(seg.get("order", 0))
            beats = parse_visual_beats(seg)
            if not beats:
                continue
            seg_assets = sorted(
                assets_by_order.get(order, []),
                key=lambda a: (a.beat_index or 0, a.created_at),
            )
            asset_paths = [
                a.local_path for a in seg_assets
                if a.local_path and Path(a.local_path).exists()
            ]
            if not asset_paths:
                continue
            audio = audio_by_order.get(order)
            words = word_segments_from_json(
                audio.word_timestamps if audio else None
            )
            duration = float(
                audio.duration_s if audio and audio.duration_s else seg.get("duration_s", 30)
            )
            narration = (seg.get("narration_text") or "")[:500]

            text_layouts: list[list | None] = []
            for i, beat in enumerate(beats):
                if not is_diagram_beat(beat):
                    text_layouts.append(None)
                    continue
                labels = beat.resolved_diagram_labels()
                if not labels:
                    text_layouts.append(None)
                    continue
                image_path = Path(
                    asset_paths[i] if i < len(asset_paths) else asset_paths[-1]
                )
                layout = await analyze_diagram_text_layout(
                    image_path,
                    labels,
                    narration_excerpt=narration,
                    language=channel_config.content_language,
                    visual_type=beat.visual_type,
                    vertical=is_short,
                    width=1080 if is_short else 1920,
                    height=1920 if is_short else 1080,
                )
                text_layouts.append(layout)

            timeline = compute_beat_timeline(
                beats,
                words,
                duration,
                min_duration_for_beat=min_for_beat,
                image_paths=asset_paths,
                text_layouts=text_layouts,
            )
            if timeline:
                timelines[order] = timeline
        return timelines

    @staticmethod
    def _validate_media_assets(
        media_assets: list[MediaAsset],
        scenario: Scenario | None = None,
    ) -> None:
        usable = [
            asset for asset in media_assets
            if asset.local_path and Path(asset.local_path).exists()
        ]
        if usable:
            return
        if scenario and scenario.segments:
            has_visual_optional = any(seg.get("visual_optional") for seg in scenario.segments)
            if has_visual_optional:
                return
        if not media_assets:
            raise RuntimeError(
                "Montage impossible : aucun média sélectionné en base. "
                "Relancez le media_agent ou vérifiez les logs de recherche média."
            )
        raise RuntimeError(
            f"Montage impossible : {len(media_assets)} média(s) en base "
            "mais aucun fichier local accessible (local_path manquant ou supprimé)."
        )

    @staticmethod
    def _validate_audio_coverage(
        scenario: Scenario | None,
        audio_files: list[AudioFile],
    ) -> None:
        if not scenario or not scenario.segments:
            return
        audio_by_order = {
            (af.segment_order or 0): af
            for af in audio_files
            if af.local_path and Path(af.local_path).exists()
        }
        missing: list[int] = []
        for seg in scenario.segments:
            if not segment_needs_voice(seg):
                continue
            order = seg.get("order", 0)
            if order not in audio_by_order:
                missing.append(order)
        if missing:
            raise RuntimeError(
                f"Segments avec narration requise mais sans fichier audio : {missing}"
            )

    async def _mix_music_by_mood(
        self,
        ctx: "PipelineContext",
        video_path: Path,
        segment_meta: dict[int, dict],
        total_duration_s: float,
    ) -> Path:
        """Mixe la musique par blocs de mood si des segments le demandent."""
        from agent.skills.audio.audio_mixer import (
            load_audio_mix_config,
            mix_multi_segment_music,
            resolve_music_volume,
        )

        if not segment_meta or not any(m.get("needs_music") for m in segment_meta.values()):
            logger.info("Mix musique ignoré — aucun segment ne demande de musique")
            return video_path

        mix_cfg = load_audio_mix_config()
        has_narration = any(m.get("needs_voice") for m in segment_meta.values())
        has_ambient = any(not m.get("strip_source_audio", True) for m in segment_meta.values())
        music_volume = resolve_music_volume(has_narration, has_ambient, mix_cfg)
        duck_narration = mix_cfg["ducking_enabled"] and has_narration

        try:
            mood_blocks = _build_mood_blocks(segment_meta, total_duration_s)
            if not mood_blocks:
                return await self._fallback_music(
                    ctx, video_path, music_volume, duck_narration
                )

            mixed_path = video_path.with_stem(video_path.stem + "_music")
            music_mixed = await mix_multi_segment_music(
                video_path,
                mood_blocks,
                mixed_path,
                music_volume=music_volume,
                duck_narration=duck_narration,
            )
            if music_mixed:
                video_path.unlink(missing_ok=True)
                return mixed_path

            logger.warning("Mix musique par mood : aucune piste trouvée, fallback thème chaîne")
            mixed_path.unlink(missing_ok=True)
            return await self._fallback_music(
                ctx, video_path, music_volume, duck_narration
            )

        except Exception as e:
            logger.warning("Mix musique par mood ignoré (erreur) : %s", e)
            return await self._fallback_music(
                ctx, video_path, music_volume, duck_narration
            )

    async def _fallback_music(
        self,
        ctx: "PipelineContext",
        video_path: Path,
        music_volume: float,
        duck_narration: bool,
    ) -> Path:
        """Fallback : une seule piste musicale basée sur le thème de la chaîne."""
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
            await mix_background_music(
                video_path,
                music_path,
                mixed_path,
                music_volume=music_volume,
                duck_narration=duck_narration,
            )
            video_path.unlink(missing_ok=True)
            return mixed_path

        except Exception as e:
            logger.warning("Musique de fond ignorée (erreur) : %s", e)
            return video_path


def _scenario_requires_audio(segment_meta: dict[int, dict]) -> bool:
    if not segment_meta:
        return True
    for meta in segment_meta.values():
        if meta.get("needs_voice") or meta.get("needs_music"):
            return True
        if not meta.get("strip_source_audio", True):
            return True
    return False


def _build_mood_blocks(
    segment_meta: dict[int, dict],
    total_duration_s: float,
) -> list[dict]:
    """Construit des blocs de mood pour les segments demandant de la musique."""
    if not segment_meta:
        return []

    ordered = sorted(segment_meta.items())
    blocks: list[dict] = []
    current_start = 0.0

    for _order, meta in ordered:
        mood = meta.get("mood", "calme")
        duration = float(meta.get("duration_s", 30))

        if meta.get("needs_music"):
            if blocks and blocks[-1]["mood"] == mood and abs(
                blocks[-1]["start_s"] + blocks[-1]["duration_s"] - current_start
            ) < 0.01:
                blocks[-1]["duration_s"] += duration
            else:
                blocks.append({"start_s": current_start, "duration_s": duration, "mood": mood})

        current_start += duration

    return blocks
