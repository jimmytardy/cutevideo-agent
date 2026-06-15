from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from agent.core.channel_config import ChannelRuntimeConfig, resolve_channel_config
from agent.core.database import AgentRun, Channel, MediaAsset, Project, Scenario
from agent.core.visual_beats import parse_visual_beats
from agent.skills.media.media_library import LIBRARY_SELECTED


@dataclass(frozen=True)
class MediaProgressData:
    iteration: int
    found: int
    total: int
    percent: int
    segments_done: int
    segments_total: int
    agent_status: str


def compute_expected_media_total(
    segments: list[dict[str, Any]] | None,
    *,
    visual_beats_enabled: bool,
    images_per_segment: int,
) -> tuple[int, int]:
    """Retourne (total_slots, segments_count)."""
    seg_list = segments or []
    segments_total = len(seg_list)
    if not seg_list:
        return 0, 0

    total = 0
    for segment in seg_list:
        if not isinstance(segment, dict):
            continue
        beats = parse_visual_beats(segment) if visual_beats_enabled else []
        if visual_beats_enabled and beats:
            total += len(beats)
        else:
            total += images_per_segment
    return total, segments_total


def build_media_progress(
    *,
    iteration: int,
    found: int,
    total: int,
    segments_done: int,
    segments_total: int,
    agent_status: str,
) -> MediaProgressData:
    percent = round(found / total * 100) if total > 0 else 0
    return MediaProgressData(
        iteration=iteration,
        found=found,
        total=total,
        percent=percent,
        segments_done=segments_done,
        segments_total=segments_total,
        agent_status=agent_status,
    )


async def compute_media_progress(
    session: AsyncSession,
    project_id: uuid.UUID,
    iteration: int | None = None,
) -> MediaProgressData:
    project_result = await session.execute(
        select(Project).where(Project.id == project_id)
    )
    project = project_result.scalar_one_or_none()
    if project is None:
        raise ValueError(f"Projet introuvable : {project_id}")

    channel_result = await session.execute(
        select(Channel).where(Channel.id == project.channel_id)
    )
    channel = channel_result.scalar_one_or_none()
    if channel is None:
        raise ValueError(f"Chaîne introuvable pour le projet {project_id}")

    channel_config: ChannelRuntimeConfig = resolve_channel_config(channel)

    scenario_result = await session.execute(
        select(Scenario)
        .where(Scenario.project_id == project_id)
        .order_by(Scenario.created_at.desc())
        .limit(1)
    )
    scenario = scenario_result.scalar_one_or_none()
    segments = list(scenario.segments or []) if scenario else []

    resolved_iteration = iteration
    if resolved_iteration is None:
        run_result = await session.execute(
            select(AgentRun)
            .where(
                AgentRun.project_id == project_id,
                AgentRun.agent_name == "media_agent",
            )
            .order_by(AgentRun.started_at.desc())
            .limit(1)
        )
        latest_run = run_result.scalar_one_or_none()
        resolved_iteration = latest_run.iteration if latest_run else (scenario.iteration if scenario else 1)

    total, segments_total = compute_expected_media_total(
        segments,
        visual_beats_enabled=channel_config.visual_beats.enabled,
        images_per_segment=channel_config.media_sources.images_per_segment,
    )

    count_result = await session.execute(
        select(func.count(MediaAsset.id)).where(
            MediaAsset.project_id == project_id,
            MediaAsset.library_status == LIBRARY_SELECTED,
            MediaAsset.iteration == resolved_iteration,
        )
    )
    found = int(count_result.scalar_one() or 0)

    segments_done_result = await session.execute(
        select(func.count(func.distinct(MediaAsset.segment_order))).where(
            MediaAsset.project_id == project_id,
            MediaAsset.library_status == LIBRARY_SELECTED,
            MediaAsset.iteration == resolved_iteration,
            MediaAsset.segment_order.is_not(None),
        )
    )
    segments_done = int(segments_done_result.scalar_one() or 0)

    run_status_result = await session.execute(
        select(AgentRun)
        .where(
            AgentRun.project_id == project_id,
            AgentRun.agent_name == "media_agent",
            AgentRun.iteration == resolved_iteration,
        )
        .order_by(AgentRun.started_at.desc())
        .limit(1)
    )
    media_run = run_status_result.scalar_one_or_none()
    agent_status = media_run.status if media_run and media_run.status else "pending"

    return build_media_progress(
        iteration=resolved_iteration,
        found=found,
        total=total,
        segments_done=segments_done,
        segments_total=segments_total,
        agent_status=agent_status,
    )
