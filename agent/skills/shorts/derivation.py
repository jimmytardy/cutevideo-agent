from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from agent.agents.narrator_agent import segment_needs_voice
from agent.core.database import AsyncSessionFactory, AudioFile, MediaAsset, Scenario, Video
from agent.core.short_derivation import DerivedShortPlan, derivation_iteration, native_video_type

if TYPE_CHECKING:
    from agent.agents.editor_agent import EditorAgent
    from agent.agents.narrator_agent import NarratorAgent
    from agent.core.orchestrator import PipelineContext

logger = logging.getLogger(__name__)


def _derivation_path_prefix(project_id: Any, short_index: int) -> str:
    return f"shorts/{short_index:02d}"


async def run_narration_for_short_derivation(
    agent: "NarratorAgent",
    ctx: "PipelineContext",
    plan: DerivedShortPlan,
) -> list[AudioFile]:
    """TTS pour un short dérivé sans effacer l'audio de la vidéo longue."""
    ctx.derivation_short_index = plan.index
    scenario = Scenario(
        project_id=ctx.project_id,
        segments=plan.segments,
        total_duration_s=plan.total_duration_s,
    )
    segments = scenario.segments or []
    voice_segments = [s for s in segments if segment_needs_voice(s)]

    output_dir = Path(f"./tmp/{ctx.project_id}/shorts/{plan.index:02d}/audio")
    output_dir.mkdir(parents=True, exist_ok=True)

    from agent.core.concurrency import bounded_gather

    tasks = [
        agent._generate_segment_audio(ctx, segment, output_dir) for segment in voice_segments
    ]
    results = await bounded_gather(*tasks, return_exceptions=True)

    audio_files: list[AudioFile] = []
    for result in results:
        if isinstance(result, AudioFile):
            audio_files.append(result)
        elif isinstance(result, Exception):
            logger.warning("Erreur audio short dérivé %d : %s", plan.index, result)

    audio_files.sort(key=lambda a: a.segment_order or 0)
    logger.info("Short dérivé %d : %d fichier(s) audio", plan.index, len(audio_files))
    return audio_files


async def run_assembly_for_short_derivation(
    agent: "EditorAgent",
    ctx: "PipelineContext",
    plan: DerivedShortPlan,
) -> Video:
    """Monte un short vertical 9:16 via MontagePlan (pas de chemin legacy)."""
    from agent.agents.montage_planner_agent import MontagePlannerAgent
    from agent.agents.editor_agent import _scenario_requires_audio
    from agent.agents.narrator_agent import segment_needs_music
    from agent.core.short_derivation import derivation_iteration
    from agent.skills.video.ffmpeg_utils import assemble_from_montage_plan, assert_audio_has_signal

    ctx.derivation_short_index = plan.index
    path_prefix = _derivation_path_prefix(ctx.project_id, plan.index)
    deriv_iteration = derivation_iteration(plan.index)

    async with AsyncSessionFactory() as session:
        media_result = await session.execute(
            select(MediaAsset)
            .where(
                MediaAsset.project_id == ctx.project_id,
                MediaAsset.selected == True,
                MediaAsset.iteration == deriv_iteration,
            )
            .order_by(MediaAsset.segment_order, MediaAsset.beat_index)
        )
        media_assets = list(media_result.scalars().all())

        if not media_assets:
            media_result = await session.execute(
                select(MediaAsset)
                .where(MediaAsset.project_id == ctx.project_id, MediaAsset.selected == True)
                .order_by(MediaAsset.segment_order, MediaAsset.beat_index)
            )
            media_assets = [
                a
                for a in media_result.scalars().all()
                if a.local_path and path_prefix in a.local_path
            ]

        audio_result = await session.execute(
            select(AudioFile)
            .where(AudioFile.project_id == ctx.project_id)
            .order_by(AudioFile.segment_order)
        )
        audio_files = [
            a
            for a in audio_result.scalars().all()
            if a.local_path and path_prefix in a.local_path
        ]

    scenario = Scenario(
        project_id=ctx.project_id,
        segments=plan.segments,
        total_duration_s=plan.total_duration_s,
    )
    agent._validate_media_assets(media_assets, scenario)

    segment_meta: dict[int, dict] = {}
    for seg in plan.segments:
        order = seg.get("order", 0)
        needs_voice = segment_needs_voice(seg)
        segment_meta[order] = {
            "on_screen_text": seg.get("on_screen_text", ""),
            "duration_s": seg.get("duration_s", 30),
            "needs_voice": needs_voice,
            "needs_music": segment_needs_music(seg),
            "mood": seg.get("mood", "calme"),
            "strip_source_audio": seg.get("strip_source_audio", needs_voice),
            "visual_optional": bool(seg.get("visual_optional", False)),
        }

    agent._validate_audio_coverage(scenario, audio_files)

    montage_plan = await MontagePlannerAgent.build_montage_plan_data(
        ctx, scenario, media_assets, audio_files,
    )
    if not montage_plan.segments:
        raise RuntimeError(
            f"Short dérivé {plan.index} : MontagePlan vide après planification"
        )

    output_dir = Path("./output/shorts/derived")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{ctx.project_id}_native{plan.index:02d}.mp4"

    duration_s = await assemble_from_montage_plan(
        montage_plan,
        audio_files=audio_files,
        output_path=output_path,
        project_id=ctx.project_id,
    )

    output_path = await agent._mix_music_by_mood(ctx, output_path, segment_meta, duration_s)

    has_narration = any(m.get("needs_voice") for m in segment_meta.values())
    await assert_audio_has_signal(
        output_path,
        min_mean_db=-50.0 if has_narration else -65.0,
        required=_scenario_requires_audio(segment_meta),
    )

    video_type = native_video_type(plan.index)
    async with AsyncSessionFactory() as session:
        video = Video(
            project_id=ctx.project_id,
            video_type=video_type,
            local_path=str(output_path),
            duration_s=duration_s,
            iteration=deriv_iteration,
            status="draft",
        )
        session.add(video)
        await session.commit()
        await session.refresh(video)

    from agent.core.storage import persist_video_to_storage

    video = await persist_video_to_storage(
        video, ctx.channel_slug, output_path, delete_local=False
    )
    logger.info(
        "Short natif dérivé %d assemblé : %s (%.1f s)",
        plan.index,
        output_path,
        duration_s,
    )
    return video
