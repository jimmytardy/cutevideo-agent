from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agent.agents.hook_optimizer_agent import HOOK_OPTIMIZABLE_KEYS
from agent.core.channel_config import resolve_channel_config
from agent.core.database import (
    AgentRun,
    AudioFile,
    Channel,
    CriticReport,
    MontagePlan,
    Project,
    Scenario,
    Video,
)
from agent.skills.media.progress import compute_media_progress
from agent.skills.pipeline_progress.models import AgentProgressData, PipelineProgressSnapshot
from agent.skills.pipeline_progress.rules import (
    build_progress,
    compute_binary_progress,
    compute_hook_progress,
    compute_media_agent_progress,
    compute_montage_progress,
    compute_narrator_progress,
    compute_research_progress,
    compute_scenario_progress,
    compute_short_editor_progress,
    count_voice_segments,
)

ITERATION_AGENT_NAMES: frozenset[str] = frozenset({
    "revision_agent",
    "media_agent",
    "narrator_agent",
    "montage_planner_agent",
    "editor_agent",
    "subtitle_agent",
    "critic_agent",
})


def _hook_segment(segments: list[Any] | None) -> dict[str, Any] | None:
    for seg in segments or []:
        if isinstance(seg, dict) and int(seg.get("order", 0) or 0) == 1:
            return seg
    return None


def _resolve_iterations(
    agent_runs: list[AgentRun],
    critic_reports: list[CriticReport],
) -> list[int]:
    iterations: set[int] = set()
    for run in agent_runs:
        if run.agent_name in ITERATION_AGENT_NAMES and run.iteration:
            iterations.add(run.iteration)
    for report in critic_reports:
        if report.iteration:
            iterations.add(report.iteration)
    if not iterations:
        iterations.add(1)
    return sorted(iterations)


async def compute_pipeline_progress(
    session: AsyncSession,
    project_id: uuid.UUID,
) -> PipelineProgressSnapshot:
    project_result = await session.execute(select(Project).where(Project.id == project_id))
    project = project_result.scalar_one_or_none()
    if project is None:
        raise ValueError(f"Projet introuvable : {project_id}")

    channel_result = await session.execute(
        select(Channel).where(Channel.id == project.channel_id)
    )
    channel = channel_result.scalar_one_or_none()
    if channel is None:
        raise ValueError(f"Chaîne introuvable pour le projet {project_id}")

    channel_config = resolve_channel_config(channel)
    project_config = project.config or {}
    planned_shorts = project_config.get("planned_shorts") or []

    scenarios_result = await session.execute(
        select(Scenario)
        .where(Scenario.project_id == project_id)
        .order_by(Scenario.created_at.desc())
    )
    scenarios = list(scenarios_result.scalars().all())
    latest_scenario = scenarios[0] if scenarios else None
    latest_segments = list(latest_scenario.segments or []) if latest_scenario else []
    scenarios_by_iteration = {
        s.iteration: s for s in scenarios if s.iteration is not None
    }

    runs_result = await session.execute(
        select(AgentRun)
        .where(AgentRun.project_id == project_id)
        .order_by(AgentRun.started_at.desc())
    )
    agent_runs = list(runs_result.scalars().all())

    reports_result = await session.execute(
        select(CriticReport)
        .join(Video, CriticReport.video_id == Video.id)
        .where(Video.project_id == project_id)
        .order_by(CriticReport.created_at.asc())
    )
    critic_reports = list(reports_result.scalars().all())
    reports_by_iteration: dict[int, CriticReport] = {}
    for idx, report in enumerate(critic_reports):
        iteration = report.iteration if report.iteration is not None else idx + 1
        reports_by_iteration[iteration] = report

    brief_raw = project_config.get("research_brief")
    brief_dict = brief_raw if isinstance(brief_raw, dict) else None

    def latest_run(agent_name: str, iteration: int | None = None) -> AgentRun | None:
        matches = [
            r for r in agent_runs
            if r.agent_name == agent_name
            and (iteration is None or r.iteration == iteration)
        ]
        return matches[0] if matches else None

    hook_run = latest_run("hook_optimizer_agent")
    if hook_run and hook_run.status == "success":
        hook_progress = build_progress(
            len(HOOK_OPTIMIZABLE_KEYS),
            len(HOOK_OPTIMIZABLE_KEYS),
            detail="Accroche optimisée",
        )
    else:
        hook_progress = compute_hook_progress(_hook_segment(latest_segments))

    preparation: dict[str, AgentProgressData] = {
        "research_agent": compute_research_progress(brief_dict),
        "scenario_agent": compute_scenario_progress(latest_segments),
        "hook_optimizer_agent": hook_progress,
    }

    iterations_map: dict[int, dict[str, AgentProgressData]] = {}
    iteration_numbers = _resolve_iterations(agent_runs, critic_reports)

    audio_result = await session.execute(
        select(AudioFile).where(AudioFile.project_id == project_id)
    )
    audio_files = list(audio_result.scalars().all())

    montage_result = await session.execute(
        select(MontagePlan)
        .where(MontagePlan.project_id == project_id)
        .order_by(MontagePlan.iteration.asc(), MontagePlan.created_at.desc())
    )
    montage_plans = list(montage_result.scalars().all())
    montage_by_iteration: dict[int, MontagePlan] = {}
    for plan in montage_plans:
        if plan.iteration not in montage_by_iteration:
            montage_by_iteration[plan.iteration] = plan

    videos_result = await session.execute(
        select(Video).where(Video.project_id == project_id)
    )
    videos = list(videos_result.scalars().all())

    for iteration in iteration_numbers:
        iter_scenario = scenarios_by_iteration.get(iteration) or latest_scenario
        iter_segments = list(iter_scenario.segments or []) if iter_scenario else []
        voice_total = count_voice_segments(iter_segments)

        audio_for_iter = {
            a.segment_order
            for a in audio_files
            if a.segment_order is not None
        }
        audio_count = len(audio_for_iter)

        montage_plan = montage_by_iteration.get(iteration)
        plan_segments = 0
        if montage_plan and montage_plan.plan_data:
            plan_segments = len(montage_plan.plan_data.get("segments") or [])

        has_video = any(
            v.iteration == iteration
            and v.video_type in ("long", "short_master")
            and (v.local_path or v.storage_key)
            for v in videos
        )

        subtitle_run = latest_run("subtitle_agent", iteration)
        subtitle_done = bool(
            subtitle_run
            and subtitle_run.status == "success"
        ) or any(
            v.iteration == iteration
            and v.local_path
            and "_subtitled" in (v.local_path or "")
            for v in videos
            if v.video_type in ("long", "short_master")
        )

        revision_done = iteration in scenarios_by_iteration and bool(
            scenarios_by_iteration[iteration].segments
        )

        try:
            media_progress = await compute_media_progress(
                session, project_id, iteration=iteration
            )
            media_item = compute_media_agent_progress(media_progress)
        except ValueError:
            media_item = build_progress(0, 0)

        critic_report = reports_by_iteration.get(iteration)

        agents: dict[str, AgentProgressData] = {}
        if iteration > 1:
            agents["revision_agent"] = compute_binary_progress(
                revision_done,
                detail="Scénario révisé" if revision_done else None,
            )
        agents["media_agent"] = media_item
        agents["narrator_agent"] = compute_narrator_progress(audio_count, voice_total)
        agents["montage_planner_agent"] = compute_montage_progress(
            plan_segments,
            len(iter_segments),
        )
        agents["editor_agent"] = compute_binary_progress(
            has_video,
            detail="Vidéo assemblée" if has_video else None,
        )
        agents["subtitle_agent"] = compute_binary_progress(
            subtitle_done,
            detail="Sous-titres" if subtitle_done else None,
        )
        agents["critic_agent"] = compute_binary_progress(
            critic_report is not None,
            detail="Rapport" if critic_report else None,
        )
        iterations_map[iteration] = agents

    clipper_run = latest_run("clipper_agent")
    clipper_done = clipper_run is not None and clipper_run.status == "success"
    clips_count = 0
    if clipper_run and clipper_run.output_json:
        clips_count = int(clipper_run.output_json.get("clips_count") or 0)

    enabled_platforms = len(channel_config.enabled_platforms or [])
    if clips_count <= 0:
        clips_count = len(planned_shorts) if planned_shorts else 5
    expected_short_exports = max(clips_count * max(enabled_platforms, 1), 1)

    short_videos = [
        v for v in videos
        if v.video_type
        and v.video_type.startswith("short_")
        and v.video_type != "short_master"
    ]
    short_editor_item = compute_short_editor_progress(
        len(short_videos),
        expected_short_exports,
    )

    post_production: dict[str, AgentProgressData] = {
        "clipper_agent": compute_binary_progress(
            clipper_done,
            detail=f"{clips_count} clips" if clipper_done else None,
        ),
        "short_editor_agent": short_editor_item,
    }

    return PipelineProgressSnapshot(
        preparation=preparation,
        iterations=iterations_map,
        post_production=post_production,
    )
