from __future__ import annotations

import logging
import uuid
from pathlib import Path

from sqlalchemy import select

from typing import Any

from agent.core.base_agent import BaseAgent
from agent.core.database import AsyncSessionFactory, AudioFile, Project, Scenario, Video
from agent.agents.narrator_agent import segment_needs_music, segment_needs_voice

logger = logging.getLogger(__name__)


class EditorAgent(BaseAgent):
    """Agent 4 — Monteur vidéo : exécute le MontagePlan (pas de chemin legacy)."""

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
        from agent.agents.montage_planner_agent import load_latest_montage_plan
        from agent.skills.video.ffmpeg_utils import assemble_from_montage_plan, assert_audio_has_signal, probe_video_duration
        from agent.skills.video.filter_graph_builder import color_grade_from_style_block

        montage_plan = await load_latest_montage_plan(ctx.project_id)
        if not montage_plan or not montage_plan.segments:
            raise RuntimeError(
                "Montage impossible : aucun MontagePlan en base. "
                "Relancez montage_planner_agent avant editor_agent."
            )

        async with AsyncSessionFactory() as session:
            audio_result = await session.execute(
                select(AudioFile)
                .where(AudioFile.project_id == ctx.project_id)
                .order_by(AudioFile.segment_order)
            )
            audio_files = list(audio_result.scalars().all())
            project = await session.get(Project, ctx.project_id)
            style_block = str((project.config or {}).get("visual_style_block", "")) if project else ""

        grade = color_grade_from_style_block(style_block)
        if grade:
            logger.info("Étalonnage final (P5) dérivé du style : %s", grade)
        segment_meta = self._build_segment_meta(scenario)
        from agent.core.short_format import (
            effective_short_max_duration_s,
            exceeds_short_duration_limit,
            requires_vertical_output,
        )

        is_vertical = montage_plan.is_vertical or requires_vertical_output(ctx)

        if is_vertical:
            output_dir = Path("./output/shorts/master")
            video_type = "short_master"
        else:
            output_dir = Path("./output/long")
            video_type = "long"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{ctx.project_id}_v{ctx.iteration}.mp4"

        duration_s = await assemble_from_montage_plan(
            montage_plan,
            audio_files=audio_files,
            output_path=output_path,
            project_id=ctx.project_id,
            grade=grade,
            force_vertical=is_vertical,
        )

        output_path = await self._mix_music_by_mood(ctx, output_path, segment_meta, duration_s)
        output_path = await self._apply_sound_design(
            ctx, output_path, segment_meta, video_duration_s=duration_s
        )

        has_narration = any(m.get("needs_voice") for m in segment_meta.values())
        await assert_audio_has_signal(
            output_path,
            min_mean_db=-50.0 if has_narration else -65.0,
            required=_scenario_requires_audio(segment_meta),
        )

        duration_s = float(await probe_video_duration(output_path))
        if requires_vertical_output(ctx) and exceeds_short_duration_limit(
            duration_s,
            target_duration_seconds=ctx.target_duration_seconds,
            channel_config=ctx.channel_config,
        ):
            from agent.skills.video.ffmpeg_utils import trim_video_to_duration

            max_s = effective_short_max_duration_s(
                ctx.target_duration_seconds,
                ctx.channel_config,
            )
            trimmed_path = output_path.with_name(f"{output_path.stem}_trimmed.mp4")
            duration_s = await trim_video_to_duration(output_path, trimmed_path, max_s)
            output_path = trimmed_path
            logger.info(
                "Short trimmé à %.1f s (plafond %d s) pour le projet %s",
                duration_s,
                max_s,
                ctx.project_id,
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
    def _build_segment_meta(scenario: Scenario | None) -> dict[int, dict]:
        segment_meta: dict[int, dict] = {}
        if not scenario or not scenario.segments:
            return segment_meta
        for seg in scenario.segments:
            order = seg.get("order", 0)
            needs_voice = segment_needs_voice(seg)
            segment_meta[order] = {
                "duration_s": seg.get("duration_s", 30),
                "needs_voice": needs_voice,
                "needs_music": segment_needs_music(seg),
                "mood": seg.get("mood", "calme"),
                "strip_source_audio": seg.get("strip_source_audio", needs_voice),
                "hook_type": seg.get("hook_type"),
            }
        return segment_meta

    @staticmethod
    def _validate_media_assets(
        media_assets: list,
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

    async def _apply_sound_design(
        self,
        ctx: "PipelineContext",
        video_path: Path,
        segment_meta: dict[int, dict],
        *,
        video_duration_s: float | None = None,
    ) -> Path:
        """P4 — pose des SFX (whoosh transitions, accent révélations, cuts beats) sur la piste finale."""
        from agent.agents.montage_planner_agent import load_latest_montage_plan
        from agent.core.config import load_agent_config
        from agent.core.montage_plan import MontagePlanData, collect_clip_cut_times
        from agent.skills.audio.sound_design import (
            apply_sfx_cues,
            build_beat_cut_cues,
            build_sfx_cues,
            merge_sfx_cues,
        )
        from agent.skills.video.montage_profile import is_short_montage, short_sfx_config

        sfx_cfg = load_agent_config().get("sfx", {})
        if not sfx_cfg.get("enabled", True):
            return video_path

        segment_cues = build_sfx_cues(segment_meta)
        beat_cues: list = []
        if is_short_montage(ctx):
            profile_sfx = short_sfx_config()
            if profile_sfx.get("beat_cuts_enabled", True):
                montage_row = await load_latest_montage_plan(ctx.project_id)
                if montage_row and montage_row.plan_data:
                    plan = MontagePlanData.from_db_dict(montage_row.plan_data)
                    cut_times = collect_clip_cut_times(plan)
                    beat_cues = build_beat_cut_cues(
                        cut_times,
                        max_per_minute=int(profile_sfx.get("max_cues_per_minute", 12)),
                        video_duration_s=video_duration_s,
                    )

        cues = merge_sfx_cues(segment_cues, beat_cues)
        if not cues:
            return video_path

        try:
            out_path = video_path.with_stem(video_path.stem + "_sfx")
            result = await apply_sfx_cues(video_path, cues, out_path)
            if result:
                video_path.unlink(missing_ok=True)
                logger.info("Design sonore : %d SFX posés", len(cues))
                return result
            out_path.unlink(missing_ok=True)
        except Exception as e:
            logger.warning("Design sonore ignoré (erreur) : %s", e)
        return video_path

    async def _fallback_music(
        self,
        ctx: "PipelineContext",
        video_path: Path,
        music_volume: float,
        duck_narration: bool,
    ) -> Path:
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
